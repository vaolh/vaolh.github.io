/* ===================================================
   Refereed — PDF Speed Reader (v2) with IndexedDB
   Dedicated reader page with left controls, center
   RSVP with focus highlight, page thumbnails,
   right panel with sections + progress
   =================================================== */
(function () {
  'use strict';

  var DB_NAME = 'refereed-reader';
  var DB_VERSION = 1;
  var STORE_NAME = 'pdfs';

  var db = null;
  var words = [];
  var sections = []; // {index, title}
  var wordIndex = 0;
  var playing = false;
  var wpm = 300;
  var fontSize = 36;
  var intervalId = null;
  var currentFileName = '';
  var pdfDoc = null; // pdf.js document reference

  // DOM
  var uploadArea = document.getElementById('reader-upload-area');
  var readerActive = document.getElementById('reader-active');
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
  var fontSlider = document.getElementById('reader-fontsize');
  var fontDisplay = document.getElementById('reader-fontsize-display');
  var progressFill = document.getElementById('reader-progress-fill');
  var progressText = document.getElementById('reader-progress');
  var pagesScroller = document.getElementById('reader-pages-scroller');
  var sectionsListEl = document.getElementById('reader-sections-list');
  var wordsReadEl = document.getElementById('reader-words-read');
  var pctFill = document.getElementById('reader-pct-fill');
  var pctText = document.getElementById('reader-pct-text');
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
      req.onsuccess = function (e) { db = e.target.result; resolve(db); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function savePDF(name, arrayBuffer) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).put({ name: name, data: arrayBuffer, savedAt: new Date().toISOString() });
      tx.oncomplete = resolve;
      tx.onerror = function () { reject(tx.error); };
    });
  }

  function getAllPDFs() {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readonly');
      var req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function getPDF(name) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readonly');
      var req = tx.objectStore(STORE_NAME).get(name);
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function deletePDF(name) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).delete(name);
      tx.oncomplete = resolve;
      tx.onerror = function () { reject(tx.error); };
    });
  }

  // Expose DB operations for app.js sidebar
  window.refereedGetAllPDFs = function () {
    if (!db) return openDB().then(function () { return getAllPDFs(); });
    return getAllPDFs();
  };
  window.refereedDeletePDF = function (name) {
    return deletePDF(name).then(refreshLibrary);
  };

  // ---- PDF Text + Sections Extraction ----

  function extractTextAndSections(arrayBuffer) {
    return pdfjsLib.getDocument({ data: arrayBuffer }).promise.then(function (pdf) {
      pdfDoc = pdf;
      var pagePromises = [];
      for (var i = 1; i <= pdf.numPages; i++) {
        pagePromises.push(pdf.getPage(i).then(function (page) { return page.getTextContent(); }));
      }
      return Promise.all(pagePromises);
    }).then(function (pagesContent) {
      var fullText = '';
      var detectedSections = [];
      var wordOffset = 0;

      pagesContent.forEach(function (content) {
        var pageLines = [];
        var lastY = null;
        content.items.forEach(function (item) {
          var y = item.transform[5];
          var fSize = item.transform[0]; // approximate font size
          if (lastY !== null && Math.abs(y - lastY) > 2) pageLines.push('\n');
          // Detect headers: larger font or all-caps short lines
          var txt = item.str.trim();
          if (txt.length > 0 && txt.length < 80 && (fSize > 13 || (txt === txt.toUpperCase() && txt.length > 3 && /[A-Z]/.test(txt)))) {
            // Heuristic: possibly a section header
            var currentWordCount = fullText.split(/\s+/).filter(function (w) { return w.length > 0; }).length;
            // Avoid duplicate consecutive section labels
            if (detectedSections.length === 0 || detectedSections[detectedSections.length - 1].title !== txt) {
              detectedSections.push({ index: currentWordCount + pageLines.join(' ').split(/\s+/).filter(function (w) { return w.length > 0; }).length, title: txt });
            }
          }
          pageLines.push(item.str);
          lastY = y;
        });
        fullText += pageLines.join(' ') + '\n\n';
      });

      fullText = cleanText(fullText);
      return { text: fullText, sections: detectedSections };
    });
  }

  function cleanText(text) {
    text = text.replace(/-\s*\n\s*/g, '');
    text = text.replace(/\n{3,}/g, '\n\n');
    text = text.replace(/^\s*\d+\s*$/gm, '');
    text = text.replace(/\n(?=[a-z])/g, ' ');
    text = text.replace(/\s{2,}/g, ' ');
    return text.trim();
  }

  function tokenize(text) {
    return text.split(/\s+/).filter(function (w) { return w.length > 0; });
  }

  // ---- Page Thumbnails ----

  function renderPageThumbnails() {
    pagesScroller.innerHTML = '';
    if (!pdfDoc) return;
    for (var i = 1; i <= Math.min(pdfDoc.numPages, 50); i++) {
      (function (pageNum) {
        pdfDoc.getPage(pageNum).then(function (page) {
          var vp = page.getViewport({ scale: 0.2 });
          var canvas = document.createElement('canvas');
          canvas.width = vp.width;
          canvas.height = vp.height;
          canvas.title = 'Page ' + pageNum;
          canvas.addEventListener('click', function () {
            // Jump to approximate word position for this page
            var approxWordIndex = Math.floor((pageNum - 1) / pdfDoc.numPages * words.length);
            wordIndex = approxWordIndex;
            showWord();
          });
          page.render({ canvasContext: canvas.getContext('2d'), viewport: vp });
          pagesScroller.appendChild(canvas);
        });
      })(i);
    }
  }

  // ---- Sections List ----

  function renderSectionsList() {
    sectionsListEl.innerHTML = '';
    if (sections.length === 0) {
      sectionsListEl.innerHTML = '<p style="color:#678;font-size:.72rem">No sections detected</p>';
      return;
    }
    // Deduplicate and limit
    var unique = [];
    var seen = new Set();
    sections.forEach(function (s) {
      var key = s.title.toLowerCase().substring(0, 40);
      if (!seen.has(key)) { seen.add(key); unique.push(s); }
    });
    unique.slice(0, 30).forEach(function (s) {
      var el = document.createElement('div');
      el.className = 'section-item';
      el.textContent = s.title.substring(0, 50);
      el.addEventListener('click', function () {
        wordIndex = Math.min(s.index, words.length - 1);
        showWord();
      });
      sectionsListEl.appendChild(el);
    });
  }

  // ---- RSVP ----

  function showWord() {
    if (words.length === 0) return;
    if (wordIndex >= words.length) {
      pause();
      rsvpWord.innerHTML = '<span>— END —</span>';
      return;
    }
    var w = words[wordIndex];
    // Highlight the "ORP" (Optimal Recognition Point) — roughly at 1/3 of word
    var orp = Math.max(0, Math.floor(w.length / 3));
    var before = escapeHtmlStr(w.substring(0, orp));
    var focus = '<span class="focus-char">' + escapeHtmlStr(w.charAt(orp)) + '</span>';
    var after = escapeHtmlStr(w.substring(orp + 1));
    rsvpWord.innerHTML = before + focus + after;
    rsvpWord.style.fontSize = fontSize + 'px';

    // Progress
    var pct = ((wordIndex + 1) / words.length * 100);
    progressFill.style.width = pct + '%';
    progressText.textContent = (wordIndex + 1) + ' / ' + words.length;
    wordsReadEl.textContent = wordIndex + 1;
    pctFill.style.width = pct + '%';
    pctText.textContent = Math.round(pct) + '%';

    // Highlight active section
    var activeIdx = -1;
    sections.forEach(function (s, i) {
      if (s.index <= wordIndex) activeIdx = i;
    });
    sectionsListEl.querySelectorAll('.section-item').forEach(function (el, i) {
      el.classList.toggle('active-section', i === activeIdx);
    });
  }

  function escapeHtmlStr(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function play() {
    if (words.length === 0) return;
    playing = true;
    playBtn.textContent = '⏸ Pause';
    clearInterval(intervalId);
    var delay = 60000 / wpm;
    intervalId = setInterval(function () {
      if (wordIndex >= words.length) { pause(); return; }
      showWord();
      wordIndex++;
    }, delay);
  }

  function pause() {
    playing = false;
    playBtn.textContent = '▶ Play';
    clearInterval(intervalId);
  }

  // ---- File Handling ----

  function loadPDFData(name, arrayBuffer) {
    currentFileName = name;
    filenameEl.textContent = name;
    uploadArea.style.display = 'none';
    readerActive.style.display = 'block';

    extractTextAndSections(arrayBuffer).then(function (result) {
      words = tokenize(result.text);
      sections = result.sections;
      wordIndex = 0;
      showWord();
      renderSectionsList();
      renderPageThumbnails();
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
        if (window.refereedRenderSidebarLibrary) window.refereedRenderSidebarLibrary();
        loadPDFData(file.name, buf);
      });
    };
    reader.readAsArrayBuffer(file);
  }

  // Expose for sidebar
  window.refereedReaderLoadFile = function (file) { handleFile(file); };
  window.refereedReaderOpenByName = function (name) {
    getPDF(name).then(function (rec) {
      if (rec) loadPDFData(rec.name, rec.data);
    });
  };

  function closeReader() {
    pause();
    words = [];
    sections = [];
    wordIndex = 0;
    currentFileName = '';
    pdfDoc = null;
    readerActive.style.display = 'none';
    uploadArea.style.display = 'block';
    rsvpWord.textContent = '';
    progressFill.style.width = '0';
    progressText.textContent = '0 / 0';
    pagesScroller.innerHTML = '';
    sectionsListEl.innerHTML = '';
  }

  // ---- Library ----

  function refreshLibrary() {
    getAllPDFs().then(function (items) {
      libraryList.innerHTML = '';
      if (items.length === 0) {
        libraryList.innerHTML = '<p style="color:#678;font-size:.8rem">No saved PDFs</p>';
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement('div');
        row.className = 'library-item';
        row.innerHTML =
          '<span class="library-item-name">' + escapeHtmlStr(item.name) + '</span>' +
          '<span class="library-item-delete" data-name="' + escapeHtmlStr(item.name) + '">✕</span>';
        row.querySelector('.library-item-name').addEventListener('click', function () {
          getPDF(item.name).then(function (rec) { if (rec) loadPDFData(rec.name, rec.data); });
        });
        row.querySelector('.library-item-delete').addEventListener('click', function (e) {
          e.stopPropagation();
          deletePDF(this.getAttribute('data-name')).then(function () {
            refreshLibrary();
            if (window.refereedRenderSidebarLibrary) window.refereedRenderSidebarLibrary();
          });
        });
        libraryList.appendChild(row);
      });
    });
  }

  // ---- Events ----

  if (dropzone) {
    dropzone.addEventListener('click', function () { fileInput.click(); });
    dropzone.addEventListener('dragover', function (e) { e.preventDefault(); this.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', function () { this.classList.remove('dragover'); });
    dropzone.addEventListener('drop', function (e) {
      e.preventDefault(); this.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
    });
  }
  if (fileInput) {
    fileInput.addEventListener('change', function () { if (this.files.length > 0) handleFile(this.files[0]); });
  }
  if (playBtn) playBtn.addEventListener('click', function () { playing ? pause() : play(); });
  if (prevBtn) prevBtn.addEventListener('click', function () { wordIndex = Math.max(0, wordIndex - 20); showWord(); });
  if (nextBtn) nextBtn.addEventListener('click', function () { wordIndex = Math.min(words.length - 1, wordIndex + 20); showWord(); });
  if (closeBtn) closeBtn.addEventListener('click', closeReader);
  if (wpmSlider) {
    wpmSlider.addEventListener('input', function () {
      wpm = parseInt(this.value, 10);
      wpmDisplay.textContent = wpm;
      if (playing) { pause(); play(); }
    });
  }
  if (fontSlider) {
    fontSlider.addEventListener('input', function () {
      fontSize = parseInt(this.value, 10);
      fontDisplay.textContent = fontSize + 'px';
      rsvpWord.style.fontSize = fontSize + 'px';
    });
  }

  // ---- Init ----
  openDB().then(function () {
    refreshLibrary();
    if (window.refereedRenderSidebarLibrary) window.refereedRenderSidebarLibrary();
  }).catch(function (err) {
    console.error('IndexedDB init failed:', err);
  });

})();
