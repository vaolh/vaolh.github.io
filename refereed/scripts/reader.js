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
  var sections = [];
  var wordIndex = 0;
  var playing = false;
  var wpm = 300;
  var fontSize = 76;
  var intervalId = null;
  var currentFileName = '';
  var pdfDoc = null;

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
  var wordsReadEl = document.getElementById('reader-words-read');
  var pctFill = document.getElementById('reader-pct-fill');
  var pctText = document.getElementById('reader-pct-text');
  var libraryList = document.getElementById('reader-library-list');
  var pageInfoEl = document.getElementById('reader-page-info');
  var pageTexts = [];

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

  window.refereedGetAllPDFs = function () {
    if (!db) return openDB().then(function () { return getAllPDFs(); });
    return getAllPDFs();
  };
  window.refereedDeletePDF = function (name) {
    return deletePDF(name).then(refreshLibrary);
  };

  // ---- Text Filtering Helpers ----

  var ECON_JOURNALS = [
    // Top general
    'American Economic Review',
    'Quarterly Journal of Economics',
    'Journal of Political Economy',
    'Review of Economic Studies',
    'Econometrica',
    'Journal of Finance',
    'Review of Financial Studies',
    'Journal of Financial Economics',
    'Economic Journal',
    'Journal of Economic Perspectives',
    'Journal of Economic Literature',
    'AEA Papers and Proceedings',
    'American Economic Journal: Applied Economics',
    'American Economic Journal: Economic Policy',
    'American Economic Journal: Macroeconomics',
    'American Economic Journal: Microeconomics',
    // Development & growth
    'Journal of Development Economics',
    'World Development',
    'Journal of Economic Growth',
    'Review of Development Economics',
    'Economic Development and Cultural Change',
    'Journal of African Economies',
    'Journal of Development Studies',
    'Developing Economies',
    // Labour & health
    'Journal of Labor Economics',
    'Journal of Human Resources',
    'Labour Economics',
    'Industrial and Labor Relations Review',
    'Journal of Health Economics',
    'Health Economics',
    'American Journal of Health Economics',
    // Public & political economy
    'Journal of Public Economics',
    'National Tax Journal',
    'Journal of Policy Analysis and Management',
    'Public Choice',
    'Journal of Law and Economics',
    'Journal of Legal Studies',
    'American Political Science Review',
    'Quarterly Journal of Political Science',
    // Trade & international
    'Journal of International Economics',
    'Review of International Economics',
    'Journal of International Money and Finance',
    'World Economy',
    'Open Economies Review',
    // IO & urban
    'RAND Journal of Economics',
    'Journal of Industrial Economics',
    'International Journal of Industrial Organization',
    'Journal of Urban Economics',
    'Regional Science and Urban Economics',
    'Journal of Regional Science',
    'Real Estate Economics',
    // Macro & money
    'Journal of Monetary Economics',
    'Journal of Money, Credit and Banking',
    'Journal of Economic Dynamics and Control',
    'Macroeconomic Dynamics',
    'Review of Economic Dynamics',
    'European Economic Review',
    'Journal of the European Economic Association',
    'Economic Policy',
    // Econometrics & methods
    'Journal of Econometrics',
    'Review of Economics and Statistics',
    'Econometric Theory',
    'Journal of Applied Econometrics',
    'Journal of Business and Economic Statistics',
    'Quantitative Economics',
    'Journal of Financial Econometrics',
    // Experimental & behavioural
    'Experimental Economics',
    'Journal of Economic Behavior and Organization',
    'Games and Economic Behavior',
    'Journal of Economic Theory',
    'Theoretical Economics',
    'Journal of Mathematical Economics',
    // Environment & agriculture
    'Journal of Environmental Economics and Management',
    'Environmental and Resource Economics',
    'American Journal of Agricultural Economics',
    'Journal of Agricultural Economics',
    'Land Economics',
    // History
    'Journal of Economic History',
    'Explorations in Economic History',
    'European Review of Economic History',
    // Other notable
    'Economic Inquiry',
    'Southern Economic Journal',
    'Oxford Economic Papers',
    'Oxford Bulletin of Economics and Statistics',
    'Scandinavian Journal of Economics',
    'Canadian Journal of Economics',
    'Journal of Economics',
    'B.E. Journal of Economic Analysis and Policy',
    'Economics Letters',
    'Economics of Education Review',
    'Journal of Housing Economics',
    'Journal of Banking and Finance',
    'Journal of Corporate Finance',
    'Journal of Financial Intermediation',
    'Journal of Financial and Quantitative Analysis',
    'Journal of Risk and Uncertainty',
    'Journal of Population Economics',
    'Demography',
    'Journal of Economic Inequality',
    // Geography & regional
    'Annals of the American Association of Geographers',
    'Annals of the Association of American Geographers',
    'Economic Geography',
    'Journal of Economic Geography',
    'Transactions of the Institute of British Geographers',
    'Progress in Human Geography',
    'Environment and Planning A',
    'Environment and Planning B',
    'Environment and Planning C',
    'Regional Studies',
    'Urban Studies',
    'Urban Geography',
    'Geographical Analysis',
    'International Journal of Geographical Information Science',
    'Political Geography',
    'Global Networks',
    'Area',
    'Geoforum',
    'Antipode',
    'Geography Compass',
    'Geographical Journal',
    'Professional Geographer',
    'Spatial Economic Analysis',
    // Mathematics
    'Annals of Mathematics',
    'Journal of the American Mathematical Society',
    'Inventiones Mathematicae',
    'Acta Mathematica',
    'Mathematische Annalen',
    'Duke Mathematical Journal',
    'Journal of the European Mathematical Society',
    'Geometric and Functional Analysis',
    'Advances in Mathematics',
    'Journal fur die reine und angewandte Mathematik',
    'Transactions of the American Mathematical Society',
    'American Journal of Mathematics',
    'Mathematische Zeitschrift',
    'Probability Theory and Related Fields',
    'Annals of Probability',
    'Annals of Statistics',
    'Journal of the Royal Statistical Society',
    'Biometrika',
    'Stochastic Processes and their Applications',
    'Mathematics of Operations Research',
    'SIAM Journal on Applied Mathematics',
    'SIAM Journal on Numerical Analysis',
    'Numerische Mathematik',
    // History
    'American Historical Review',
    'Journal of Modern History',
    'Past and Present',
    'Journal of World History',
    'Economic History Review',
    'Business History Review',
    'Journal of Social History',
    'History and Theory',
    'Comparative Studies in Society and History',
    'Journal of Interdisciplinary History',
    'Historical Journal',
    'English Historical Review',
    'French Historical Studies',
    'Central European History',
    'Journal of Latin American Studies',
    'Journal of African History',
    'International Journal of Middle East Studies',
    'Journal of Asian Studies',
    'Technology and Culture',
    'History of Political Economy',
    'History of Political Thought',
    'History of Science',
    // Philosophy
    'Journal of Philosophy',
    'Mind',
    'Nous',
    'Ethics',
    'Philosophy and Public Affairs',
    'Philosophical Review',
    'Philosophical Studies',
    'Analysis',
    'Synthese',
    'British Journal for the Philosophy of Science',
    'Philosophy of Science',
    'Erkenntnis',
    'Australasian Journal of Philosophy',
    'Canadian Journal of Philosophy',
    'European Journal of Philosophy',
    'Philosophers Imprint',
    'Philosophy and Phenomenological Research',
    'Journal of Political Philosophy',
    'Social Philosophy and Policy',
    'Economics and Philosophy',
    'Philosophy and Economics',
    'Episteme',
    'Philosophical Quarterly',
    'Philosophical Perspectives',
    'Legal Theory',
  ];

  function isJournalHeader(line) {
    var t = line.trim();
    // ALL CAPS running head: "3130 THE AMERICAN ECONOMIC REVIEW OCTOBER 2024"
    if (/^\d{1,5}\s{1,4}[A-Z][A-Z\s]{6,}[A-Z]\s+[A-Z][a-z]+\s+\d{4}\s*$/.test(t)) return true;
    // ALL CAPS + VOL
    if (/^[A-Z][A-Z\s]{10,}[A-Z]\s+VOL\.?\s*\d/i.test(t)) return true;
    // DOI line
    if (/^https?:\/\/(dx\.)?doi\.org\//.test(t)) return true;
    // Named journal citation: "American Economic Review 2024, 114(10): 3119-3160"
    for (var i = 0; i < ECON_JOURNALS.length; i++) {
      if (t.indexOf(ECON_JOURNALS[i]) === 0 && /\d{4}/.test(t)) return true;
    }
    return false;
  }

  function isPageNumber(line) {
    return /^\s*\d{2,4}\s*$/.test(line);
  }

  function isTableDataRow(line) {
    var tokens = line.trim().split(/\s+/);
    if (tokens.length < 3) return false;
    var numericTokens = tokens.filter(function (t) {
      return /^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(t) || /^-?\d+(\.\d+)?$/.test(t);
    });
    return numericTokens.length >= 4 && (numericTokens.length / tokens.length) > 0.35;
  }



  function isJSTORWatermark(line) {
    var t = line.trim();
    if (/^This content downloaded from/i.test(t)) return true;
    if (/^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\s+on\s+/i.test(t)) return true;
    if (/^All use subject to https?:\/\/about\.jstor\.org/i.test(t)) return true;
    return false;
  }

  function isTableLabel(line) {
    return /^\s*(Table|Figure|Appendix Table|Appendix Figure)\s+[A-Z0-9]+(\.\d+)?/i.test(line);
  }

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
      var perPage = [];

      pagesContent.forEach(function (content) {
        // --- Column-aware extraction ---
        // 1. Collect all items with their x, y, text
        var items = content.items.map(function (item) {
          return { x: item.transform[4], y: item.transform[5], fSize: item.transform[0], str: item.str };
        }).filter(function (it) { return it.str.trim().length > 0; });

        if (items.length === 0) { perPage.push(''); return; }

        // 2. Detect columns by finding a gap in the x-distribution
        var xs = items.map(function (it) { return it.x; }).sort(function (a, b) { return a - b; });
        var pageWidth = xs[xs.length - 1] - xs[0];
        var midX = xs[0] + pageWidth / 2;

        // Find the largest gap near the middle third of the page
        var colSplit = null;
        var maxGap = 0;
        var lo = xs[0] + pageWidth * 0.3;
        var hi = xs[0] + pageWidth * 0.7;
        for (var gi = 1; gi < xs.length; gi++) {
          var gap = xs[gi] - xs[gi - 1];
          if (xs[gi - 1] >= lo && xs[gi] <= hi && gap > maxGap) {
            maxGap = gap;
            colSplit = (xs[gi - 1] + xs[gi]) / 2;
          }
        }
        // Only treat as two-column if gap is meaningful (>5% of page width)
        var isTwoCol = colSplit !== null && maxGap > pageWidth * 0.05;

        // 3. Split items into columns
        var cols = isTwoCol
          ? [items.filter(function (it) { return it.x < colSplit; }),
             items.filter(function (it) { return it.x >= colSplit; })]
          : [items];

        // 4. For each column, sort by descending Y (top to bottom), group into lines
        var pageText = '';
        cols.forEach(function (colItems) {
          colItems.sort(function (a, b) { return b.y - a.y || a.x - b.x; });
          var lines = [];
          var currentLine = [];
          var lastY = null;
          colItems.forEach(function (it) {
            if (lastY !== null && Math.abs(it.y - lastY) > 2) {
              if (currentLine.length > 0) lines.push(currentLine);
              currentLine = [];
            }
            currentLine.push(it);
            lastY = it.y;
          });
          if (currentLine.length > 0) lines.push(currentLine);

          lines.forEach(function (line) {
            var lineStr = line.map(function (it) { return it.str; }).join(' ').trim();
            // Section detection
            var fSize = line[0].fSize;
            var txt = lineStr.trim();
            if (txt.length > 0 && txt.length < 80 && (fSize > 13 || (txt === txt.toUpperCase() && txt.length > 3 && /[A-Z]/.test(txt)))) {
              var currentWordCount = fullText.split(/\s+/).filter(function (w) { return w.length > 0; }).length;
              if (detectedSections.length === 0 || detectedSections[detectedSections.length - 1].title !== txt) {
                detectedSections.push({ index: currentWordCount, title: txt });
              }
            }
            pageText += lineStr + '\n';
          });
        });

        perPage.push(pageText.trim());
        fullText += pageText + '\n\n';
      });

      fullText = cleanText(fullText);
      return { text: fullText, sections: detectedSections, pageTexts: perPage };
    });
  }

  function cleanText(text) {
    // 1. Basic normalisation
    text = text.replace(/-\s*\n\s*/g, '');
    text = text.replace(/\n{3,}/g, '\n\n');

    // 2. Line-level filtering
    var lines = text.split('\n');
    var filtered = [];

    lines.forEach(function (line) {
      var trimmed = line.trim();

      // Start of Notes/Source block — skip until blank line
      // Drop journal running-heads and bare page numbers
      if (isJournalHeader(trimmed) || isPageNumber(trimmed) || isJSTORWatermark(trimmed)) return;

      // Drop table data rows; keep label lines shortened
      if (isTableDataRow(trimmed)) {
        if (isTableLabel(trimmed)) {
          var label = trimmed.replace(/[—–].*/g, '').replace(/\s{2,}/g, ' ').trim();
          filtered.push(label);
        }
        return;
      }

      filtered.push(line);
    });

    text = filtered.join('\n');

    // 3. Final cleanup
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
          var vp = page.getViewport({ scale: 0.12 });
          var canvas = document.createElement('canvas');
          canvas.width = vp.width;
          canvas.height = vp.height;
          canvas.title = 'Page ' + pageNum;
          canvas.addEventListener('click', function () {
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

  // ---- RSVP ----

  function showWord() {
    if (words.length === 0) return;
    if (wordIndex >= words.length) {
      pause();
      rsvpWord.innerHTML = '<span>— END —</span>';
      return;
    }
    var w = words[wordIndex];
    var orp = Math.max(0, Math.floor(w.length / 3));
    var before = escapeHtmlStr(w.substring(0, orp));
    var focus = '<span class="focus-char">' + escapeHtmlStr(w.charAt(orp)) + '</span>';
    var after = escapeHtmlStr(w.substring(orp + 1));
    rsvpWord.innerHTML = before + focus + after;
    rsvpWord.style.fontSize = fontSize + 'px';

    var pct = ((wordIndex + 1) / words.length * 100);
    progressFill.style.width = pct + '%';
    progressText.textContent = Math.round(pct) + '%';
    wordsReadEl.textContent = wordIndex + 1;
    if (pctFill) pctFill.style.width = pct + '%';
    if (pctText) pctText.textContent = Math.round(pct) + '%';

    if (pdfDoc && pageTexts.length > 0) {
      var approxPage = Math.min(Math.floor(wordIndex / words.length * pdfDoc.numPages), pdfDoc.numPages - 1);
      pageInfoEl.textContent = 'Page ' + (approxPage + 1) + ' of ' + pdfDoc.numPages;
      var canvases = pagesScroller.querySelectorAll('canvas');
      canvases.forEach(function (c, i) { c.classList.toggle('active-page', i === approxPage); });
    }
  }

  function escapeHtmlStr(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function play() {
    if (words.length === 0) return;
    playing = true;
    playBtn.classList.add('playing');
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
    playBtn.classList.remove('playing');
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
      pageTexts = result.pageTexts || [];
      wordIndex = 0;
      showWord();
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
    pageTexts = [];
    wordIndex = 0;
    currentFileName = '';
    pdfDoc = null;
    readerActive.style.display = 'none';
    uploadArea.style.display = 'block';
    rsvpWord.textContent = '';
    progressFill.style.width = '0';
    progressText.textContent = '0%';
    pagesScroller.innerHTML = '';
    pageInfoEl.textContent = '';
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
      fontDisplay.textContent = fontSize;
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