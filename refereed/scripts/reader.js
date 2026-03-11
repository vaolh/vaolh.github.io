/* ===================================================
   Refereed — PDF Speed Reader (RSVP) with IndexedDB
   =================================================== */

(function () {
  'use strict';

  var DB_NAME = 'refereed-reader';
  var DB_VERSION = 1;
  var STORE_NAME = 'pdfs';

  var db = null;
  var words = [];
  var wordIndex = 0;
  var playing = false;
  var wpm = 300;
  var intervalId = null;
  var currentFileName = '';

  // ---- DOM refs ----
  var controlsBar = document.getElementById('reader-controls-bar');
  var uploadArea = document.getElementById('reader-upload-area');
  var dropzone = document.getElementById('upload-dropzone');
  var fileInput = document.getElementById('pdf-file-input');
  var filenameEl = document.getElementById('reader-filename');
  var closeBtn = document.getElementById('reader-close-btn');
  var rsvpWord = document.getElementById('rsvp-word');
  var playBtn = document.getElementById('reader-play');
  var prevBtn = document.getElementById('reader-prev');
  var nextBtn = document.getElementById('reader-next');
  var wpmSlider = document.getElementById('reader-wpm');
  var wpmDisplay = document.getElementById('reader-wpm-display');
  var progressEl = document.getElementById('reader-progress');
  var libraryList = document.getElementById('reader-library-list');

  // ---- IndexedDB ----

  function openDB() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var d = e.target.result;
        if (!d.objectStoreNames.contains(STORE_NAME)) {
          d.createObjectStore(STORE_NAME, { keyPath: 'name' });
        }
      };
      req.onsuccess = function (e) {
        db = e.target.result;
        resolve(db);
      };
      req.onerror = function () { reject(req.error); };
    });
  }

  function savePDF(name, arrayBuffer) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      store.put({ name: name, data: arrayBuffer, savedAt: new Date().toISOString() });
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  function getAllPDFs() {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function getPDF(name) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.get(name);
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function deletePDF(name) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      store.delete(name);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  // ---- PDF Text Extraction ----

  function extractText(arrayBuffer) {
    return pdfjsLib.getDocument({ data: arrayBuffer }).promise.then(function (pdf) {
      var pagePromises = [];
      for (var i = 1; i <= pdf.numPages; i++) {
        pagePromises.push(
          pdf.getPage(i).then(function (page) {
            return page.getTextContent();
          })
        );
      }
      return Promise.all(pagePromises);
    }).then(function (pagesContent) {
      var fullText = '';
      pagesContent.forEach(function (content) {
        var pageLines = [];
        var lastY = null;
        content.items.forEach(function (item) {
          var y = item.transform[5];
          if (lastY !== null && Math.abs(y - lastY) > 2) {
            pageLines.push('\n');
          }
          pageLines.push(item.str);
          lastY = y;
        });
        fullText += pageLines.join(' ') + '\n\n';
      });
      return cleanText(fullText);
    });
  }

  function cleanText(text) {
    // Heuristics: join hyphenated line breaks, remove headers/page numbers, clean up
    text = text.replace(/-\s*\n\s*/g, '');          // rejoin hyphenated words
    text = text.replace(/\n{3,}/g, '\n\n');          // collapse excessive newlines
    text = text.replace(/^\s*\d+\s*$/gm, '');       // remove standalone page numbers
    text = text.replace(/\n(?=[a-z])/g, ' ');        // join lines mid-sentence
    text = text.replace(/\s{2,}/g, ' ');             // collapse whitespace
    return text.trim();
  }

  function tokenize(text) {
    return text.split(/\s+/).filter(function (w) { return w.length > 0; });
  }

  // ---- RSVP Controls ----

  function showWord() {
    if (wordIndex >= words.length) {
      pause();
      rsvpWord.textContent = '— END —';
      return;
    }
    rsvpWord.textContent = words[wordIndex];
    progressEl.textContent = (wordIndex + 1) + ' / ' + words.length;
  }

  function play() {
    if (words.length === 0) return;
    playing = true;
    playBtn.textContent = '⏸ Pause';
    clearInterval(intervalId);
    var delay = 60000 / wpm;
    intervalId = setInterval(function () {
      if (wordIndex >= words.length) {
        pause();
        return;
      }
      showWord();
      wordIndex++;
    }, delay);
  }

  function pause() {
    playing = false;
    playBtn.textContent = '▶ Play';
    clearInterval(intervalId);
  }

  function jumpBack() {
    wordIndex = Math.max(0, wordIndex - 20);
    showWord();
  }

  function jumpForward() {
    wordIndex = Math.min(words.length - 1, wordIndex + 20);
    showWord();
  }

  // ---- File Handling ----

  function loadPDFData(name, arrayBuffer) {
    currentFileName = name;
    extractText(arrayBuffer).then(function (text) {
      words = tokenize(text);
      wordIndex = 0;
      filenameEl.textContent = name;
      controlsBar.style.display = 'block';
      uploadArea.style.display = 'none';
      showWord();
    }).catch(function (err) {
      console.error('PDF extraction failed:', err);
      rsvpWord.textContent = 'Error reading PDF';
    });
  }

  function handleFile(file) {
    if (!file || file.type !== 'application/pdf') return;
    var reader = new FileReader();
    reader.onload = function (e) {
      var buf = e.target.result;
      savePDF(file.name, buf).then(function () {
        refreshLibrary();
        loadPDFData(file.name, buf);
      });
    };
    reader.readAsArrayBuffer(file);
  }

  function closeReader() {
    pause();
    words = [];
    wordIndex = 0;
    currentFileName = '';
    controlsBar.style.display = 'none';
    uploadArea.style.display = 'block';
    rsvpWord.textContent = '';
    progressEl.textContent = '0 / 0';
  }

  // ---- Library ----

  function refreshLibrary() {
    getAllPDFs().then(function (items) {
      libraryList.innerHTML = '';
      if (items.length === 0) {
        libraryList.innerHTML = '<p style="color:#678;font-size:0.8rem;">No saved PDFs</p>';
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement('div');
        row.className = 'library-item';
        row.innerHTML =
          '<span class="library-item-name">' + escapeAttr(item.name) + '</span>' +
          '<span class="library-item-delete" data-name="' + escapeAttr(item.name) + '">✕</span>';
        row.querySelector('.library-item-name').addEventListener('click', function () {
          getPDF(item.name).then(function (rec) {
            if (rec) loadPDFData(rec.name, rec.data);
          });
        });
        row.querySelector('.library-item-delete').addEventListener('click', function (e) {
          e.stopPropagation();
          var n = this.getAttribute('data-name');
          deletePDF(n).then(function () { refreshLibrary(); });
        });
        libraryList.appendChild(row);
      });
    });
  }

  function escapeAttr(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ---- Event Listeners ----

  dropzone.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () {
    if (this.files.length > 0) handleFile(this.files[0]);
  });
  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    this.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', function () {
    this.classList.remove('dragover');
  });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    this.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
  });

  playBtn.addEventListener('click', function () {
    if (playing) pause(); else play();
  });
  prevBtn.addEventListener('click', jumpBack);
  nextBtn.addEventListener('click', jumpForward);
  closeBtn.addEventListener('click', closeReader);

  wpmSlider.addEventListener('input', function () {
    wpm = parseInt(this.value, 10);
    wpmDisplay.textContent = wpm;
    if (playing) { pause(); play(); }
  });

  // ---- Init ----
  openDB().then(function () {
    refreshLibrary();
  }).catch(function (err) {
    console.error('IndexedDB init failed:', err);
  });

})();
