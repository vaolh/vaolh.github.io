/* ===================================================
   Refereed — Main Application Script (v2)
   =================================================== */
(function () {
  'use strict';

  var papers = [];
  var readlist = [];
  var restoring = false;

  // ---- Helpers ----

  function ratingToStars(r) {
    if (!r) return '';
    var full = Math.floor(r);
    var half = r % 1 >= 0.5;
    return '★'.repeat(full) + (half ? '½' : '');
  }

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    if (!text) return '';
    var html = escapeHtml(text);
    var displayMath = [];
    html = html.replace(/\$\$([\s\S]*?)\$\$/g, function (_, m) {
      displayMath.push(m); return '%%DM' + (displayMath.length - 1) + '%%';
    });
    var inlineMath = [];
    html = html.replace(/\$(?!\d)([^\$\n]+?)\$/g, function (_, m) {
      inlineMath.push(m); return '%%IM' + (inlineMath.length - 1) + '%%';
    });
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/^(\d+)\.\s+(.+)$/gm, '<li>$2</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, function (m) { return '<ol>' + m + '</ol>'; });
    html = html.replace(/\n{2,}/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p>\s*<\/p>/g, '');
    displayMath.forEach(function (m, i) { html = html.replace('%%DM' + i + '%%', '\\[' + m + '\\]'); });
    inlineMath.forEach(function (m, i) { html = html.replace('%%IM' + i + '%%', '\\(' + m + '\\)'); });
    return html;
  }

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function monthKey(iso) {
    if (!iso) return 'Unknown';
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long' });
  }

  function currentYear() { return new Date().getFullYear(); }

  // ---- Navigation ----

  var pnavLinks = document.querySelectorAll('.pnav-link');
  var snavLinks = document.querySelectorAll('.snav-link');
  var pages = document.querySelectorAll('.page');
  var subpageNav = document.getElementById('subpage-nav');

  function showPage(name) {
    pages.forEach(function (p) { p.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    var target = document.getElementById('page-' + name);
    if (target) target.classList.add('active');
    if (name === 'profile') {
      subpageNav.style.display = 'none';
    } else {
      subpageNav.style.display = 'block';
    }
    var plink = document.querySelector('.pnav-link[data-page="' + name + '"]');
    if (plink) plink.classList.add('active');
    var slink = document.querySelector('.snav-link[data-page="' + name + '"]');
    if (slink) slink.classList.add('active');
    window.scrollTo(0, 0);
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise().catch(function () {});
    }
  }

  // Expose showPage globally for reader.js
  window.refereedShowPage = showPage;

  function routeHash(hash) {
    var slash = hash.indexOf('/');
    var segment = slash === -1 ? hash : hash.slice(0, slash);
    var param = slash === -1 ? '' : hash.slice(slash + 1);
    restoring = true;
    try {
      if (segment === 'review') openReview(decodeURIComponent(param));
      else if (segment === 'author') openAuthorDetail(decodeURIComponent(param));
      else if (segment === 'journal') openJournalDetail(decodeURIComponent(param));
      else if (segment === 'list') openListDetail(decodeURIComponent(param));
      else if (segment === 'rating') openRatingDetail(parseFloat(param));
      else if (segment) showPage(segment);
      else showPage('profile');
    } finally {
      restoring = false;
    }
  }

  function attachNavListeners(links) {
    links.forEach(function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var page = this.getAttribute('data-page');
        showPage(page);
        history.pushState({ page: page }, '', '#' + page);
      });
    });
  }
  attachNavListeners(pnavLinks);
  attachNavListeners(snavLinks);

  window.addEventListener('popstate', function (e) {
    routeHash(location.hash.slice(1) || 'profile');
  });

  // ---- Data Loading ----

  function loadData() {
    return Promise.all([
      fetch('data/papers.json').then(function (r) { return r.json(); }),
      fetch('data/readlist.json').then(function (r) { return r.json(); })
    ]).then(function (res) {
      papers = res[0];
      readlist = res[1];
    });
  }

  // ---- Abanico builder ----

  function buildAbanico(container, items, maxItems) {
    container.innerHTML = '';
    var list = items.slice(0, maxItems || 5);
    list.forEach(function (p, i) {
      var card = document.createElement('div');
      card.className = 'abanico-card';
      card.style.zIndex = list.length - i;
      card.innerHTML = '<img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">';
      if (p.review) {
        card.addEventListener('click', function () { openReview(p.id); });
      }
      container.appendChild(card);
    });
  }

  // ---- Profile Stats ----

  function renderStats() {
    document.getElementById('stat-total').textContent = papers.length;
    var yr = papers.filter(function (p) {
      return p.date_read && p.date_read.startsWith(String(currentYear()));
    }).length;
    document.getElementById('stat-year').textContent = yr;
    var allAuthors = new Set();
    papers.forEach(function (p) { if (p.authors) p.authors.forEach(function (a) { allAuthors.add(a); }); });
    document.getElementById('stat-authors').textContent = allAuthors.size;
    document.getElementById('stat-toread').textContent = readlist.length;
  }

  // ---- Favorites (4 posters, no stars) ----

  function renderFavorites() {
    var grid = document.getElementById('favorites-grid');
    grid.innerHTML = '';
    var favs = papers.filter(function (p) { return p.favorite; });
    favs.slice(0, 4).forEach(function (p) {
      grid.appendChild(makePosterItem(p, { showStars: false, showHover: true }));
    });
  }

  // ---- Recent Activity (4 posters with gray stars below) ----

  function renderRecentActivity() {
    var grid = document.getElementById('recent-activity');
    grid.innerHTML = '';
    var sorted = papers.slice().sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    sorted.slice(0, 4).forEach(function (p) {
      grid.appendChild(makePosterItem(p, { showStars: false, showHover: true }));
    });
  }

  // ---- Random Reviews (2 mini reviews) ----

  function renderRandomReviews() {
    var container = document.getElementById('random-reviews');
    container.innerHTML = '';
    var withReview = papers.filter(function (p) { return p.review; });
    // Shuffle
    for (var i = withReview.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = withReview[i]; withReview[i] = withReview[j]; withReview[j] = t;
    }
    withReview.slice(0, 2).forEach(function (p) {
      var el = document.createElement('div');
      el.className = 'mini-review';
      var excerpt = p.review.substring(0, 200).replace(/\$[^$]*\$/g, '[math]');
      el.innerHTML =
        '<div class="mini-review-poster"><img src="' + escapeHtml(p.poster) + '" loading="lazy"></div>' +
        '<div class="mini-review-body">' +
          '<div class="mini-review-title">' + escapeHtml(p.title) + '</div>' +
          '<div class="mini-review-stars"><span class="stars">' + ratingToStars(p.rating) + '</span></div>' +
          '<div class="mini-review-excerpt">' + escapeHtml(excerpt) + '…</div>' +
        '</div>';
      el.addEventListener('click', function () { openReview(p.id); });
      container.appendChild(el);
    });
  }

  // ---- Poster Item builder (used in profile rows) ----

  function makePosterItem(p, opts) {
    var el = document.createElement('div');
    el.className = 'poster-item';
    var hoverTitle = opts.showHover
      ? '<div class="poster-hover-title">' + escapeHtml(p.title) + '</div>'
      : '';
    var metaHtml = '';
    if (opts.showStars) {
      metaHtml = '<div class="poster-item-meta"><span class="stars">' + ratingToStars(p.rating) + '</span></div>';
    }
    el.innerHTML =
      '<div class="poster-item-img"><img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' + hoverTitle + '</div>' +
      metaHtml;
    el.addEventListener('click', function () {
      if (p.review) openReview(p.id);
    });
    return el;
  }

  // ---- Poster Card builder (used in grids) ----

  function makePosterCard(p, opts) {
    var el = document.createElement('div');
    el.className = 'poster-card' + (opts.noHover ? ' readlist-no-hover' : '');
    var hoverTitle = !opts.noHover
      ? '<div class="poster-hover-title">' + escapeHtml(p.title) + '</div>'
      : '';
    var metaHtml = '';
    if (opts.showStars) {
      metaHtml = '<div class="poster-card-meta"><span class="stars">' + ratingToStars(p.rating) + '</span></div>';
    }
    el.innerHTML =
      '<div class="poster-card-img"><img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' + hoverTitle + '</div>' +
      metaHtml;
    el.addEventListener('click', function () {
      if (p.review) openReview(p.id);
    });
    return el;
  }

  // ---- Sidebar ----

  function renderSidebarReadlist() {
    var container = document.getElementById('sidebar-readlist');
    buildAbanico(container, readlist, 5);
  }

  function renderSidebarDiary() {
    var container = document.getElementById('sidebar-diary');
    container.innerHTML = '';
    var sorted = papers.slice().sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    sorted.slice(0, 5).forEach(function (p) {
      var el = document.createElement('div');
      el.className = 'sidebar-diary-item';
      el.innerHTML =
        '<div class="sdi-title">' + escapeHtml(p.title) + '</div>' +
        '<div class="sdi-meta"><span class="stars">' + ratingToStars(p.rating) + '</span> · ' + formatDate(p.date_read) + '</div>';
      el.style.cursor = 'pointer';
      el.addEventListener('click', function () { openReview(p.id); });
      container.appendChild(el);
    });
  }

  function renderSidebarHistogram() {
    var container = document.getElementById('sidebar-histogram');
    container.innerHTML = '';
    var buckets = {};
    for (var b = 0.5; b <= 5; b += 0.5) buckets[b] = 0;
    papers.forEach(function (p) {
      if (p.rating && buckets[p.rating] !== undefined) buckets[p.rating]++;
    });
    var max = Math.max.apply(null, Object.values(buckets).concat([1]));
    var maxPx = 52;
    Object.keys(buckets).sort(function (a, b) { return a - b; }).forEach(function (k) {
      var count = buckets[k];
      var h = count > 0 ? Math.max(Math.round((count / max) * maxPx), 3) : 2;
      var bar = document.createElement('div');
      bar.className = 'hbar';
      bar.style.height = h + 'px';
      bar.innerHTML = '<span class="hbar-label">' + k + '</span>';
      bar.title = k + '\u2605: ' + count;
      bar.addEventListener('click', (function (rating) {
        return function () { openRatingDetail(parseFloat(rating)); };
      })(k));
      container.appendChild(bar);
    });
  }

  // Sidebar reader upload
  (function () {
    var dropzone = document.getElementById('sidebar-upload-dropzone');
    var input = document.getElementById('sidebar-pdf-input');
    if (!dropzone || !input) return;
    dropzone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () {
      if (this.files.length > 0) {
        // Store file in IndexedDB via reader module, then navigate
        if (window.refereedReaderLoadFile) {
          window.refereedReaderLoadFile(this.files[0]);
        }
        showPage('reader');
        history.pushState({ page: 'reader' }, '', '#reader');
      }
    });
  })();

  // ---- Papers Grid ----

  function renderPapers() {
    var grid = document.getElementById('papers-grid');
    grid.innerHTML = '';
    papers.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
    });
  }

  // ---- Diary ----

  function renderDiary() {
    var container = document.getElementById('diary-entries');
    container.innerHTML = '';
    var sorted = papers.slice().sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    var groups = {};
    sorted.forEach(function (p) {
      var mk = monthKey(p.date_read);
      if (!groups[mk]) groups[mk] = [];
      groups[mk].push(p);
    });
    Object.keys(groups).forEach(function (mk) {
      var sec = document.createElement('div');
      sec.className = 'diary-month';
      sec.innerHTML = '<h3>' + mk + '</h3>';
      groups[mk].forEach(function (p) {
        var entry = document.createElement('div');
        entry.className = 'diary-entry';
        entry.innerHTML =
          '<div class="diary-entry-poster"><img src="' + escapeHtml(p.poster) + '" loading="lazy"></div>' +
          '<div class="diary-entry-info">' +
            '<div class="diary-entry-title">' + escapeHtml(p.title) + '</div>' +
            '<div class="diary-entry-meta"><span class="stars">' + ratingToStars(p.rating) + '</span></div>' +
          '</div>' +
          '<div class="diary-entry-date">' + formatDate(p.date_read) + '</div>';
        entry.addEventListener('click', function () { openReview(p.id); });
        sec.appendChild(entry);
      });
      container.appendChild(sec);
    });
  }

  // ---- Readlist ----

  function renderReadlist() {
    var grid = document.getElementById('readlist-grid');
    grid.innerHTML = '';
    readlist.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: false, noHover: false }));
    });
  }

  // ---- Lists (abanicos, 2 per row) ----

  function renderLists() {
    var container = document.getElementById('lists-container');
    container.innerHTML = '';
    var genreMap = {};
    papers.forEach(function (p) {
      if (!p.genre) return;
      var g = p.genre.toLowerCase();
      if (!genreMap[g]) genreMap[g] = [];
      genreMap[g].push(p);
    });
    readlist.forEach(function (p) {
      if (!p.genre) return;
      var g = p.genre.toLowerCase();
      if (!genreMap[g]) genreMap[g] = [];
      if (!genreMap[g].find(function (x) { return x.id === p.id; })) genreMap[g].push(p);
    });
    Object.keys(genreMap).sort().forEach(function (genre) {
      var items = genreMap[genre];
      var label = genre.charAt(0).toUpperCase() + genre.slice(1);
      var listEl = document.createElement('div');
      listEl.className = 'list-item';
      listEl.innerHTML =
        '<h3>' + escapeHtml(label) + '</h3>' +
        '<p>' + items.length + ' paper' + (items.length !== 1 ? 's' : '') + '</p>' +
        '<div class="abanico" data-genre="' + escapeHtml(genre) + '"></div>';
      listEl.addEventListener('click', function () { openListDetail(genre); });
      container.appendChild(listEl);
      // Build abanico after it's in DOM
      var abContainer = listEl.querySelector('.abanico');
      // Need a tiny delay for offsetWidth
      setTimeout(function () { buildAbanico(abContainer, items, 5); }, 0);
    });
  }

  // ---- Review Detail ----

  function openReview(id) {
    var p = papers.find(function (x) { return x.id === id; });
    if (!p) return;
    var container = document.getElementById('review-detail-content');
    container.innerHTML =
      '<a href="#" class="back-link" id="review-back">← Back</a>' +
      '<div class="review-detail">' +
        '<div class="review-detail-top">' +
          '<div class="review-detail-poster"><img src="' + escapeHtml(p.poster) + '" alt=""></div>' +
          '<div class="review-detail-info">' +
            '<h1>' + escapeHtml(p.title) + '</h1>' +
            '<div class="review-detail-year">' + p.year + '</div>' +
            '<div class="review-detail-authors" id="review-detail-authors-links"></div>' +
            (p.journal ? '<div class="review-detail-journal"><a href="#" class="journal-link" data-journal="' + escapeHtml(p.journal) + '">' + escapeHtml(p.journal) + '</a>' + (p.detail ? ' ' + escapeHtml(p.detail) : '') + '</div>' : '') +
            '<div class="review-detail-genre">' + escapeHtml(p.genre || '') + '</div>' +
            '<div class="review-detail-rating"><span class="stars">' + ratingToStars(p.rating) + '</span>' +
            '</div>' +
            '<div class="review-detail-date">Read ' + formatDate(p.date_read) + '</div>' +
            (p.pdf ? '<div style="margin-top:8px"><a href="' + escapeHtml(p.pdf) + '" target="_blank" rel="noopener noreferrer" style="font-size:.85rem">View PDF →</a></div>' : '') +
          '</div>' +
        '</div>' +
        '<div class="review-detail-body">' + renderMarkdown(p.review) + '</div>' +
      '</div>';

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-review-detail').classList.add('active');
    subpageNav.style.display = 'block';
    window.scrollTo(0, 0);
    if (!restoring) {
      history.pushState({ page: 'review', id: id }, '', '#review/' + encodeURIComponent(id));
    }

    document.getElementById('review-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });

    // Make authors clickable
    var authorsContainer = document.getElementById('review-detail-authors-links');
    if (authorsContainer && p.authors) {
      authorsContainer.innerHTML = '';
      p.authors.forEach(function (author, idx) {
        var link = document.createElement('a');
        link.href = '#';
        link.className = 'author-link';
        link.textContent = author;
        link.addEventListener('click', function (e) {
          e.preventDefault();
          openAuthorDetail(author);
        });
        authorsContainer.appendChild(link);
        if (idx < p.authors.length - 1) {
          authorsContainer.appendChild(document.createTextNode(', '));
        }
      });
    }

    // Make journal clickable
    var journalLink = container.querySelector('.journal-link');
    if (journalLink) {
      journalLink.addEventListener('click', function (e) {
        e.preventDefault();
        openJournalDetail(this.getAttribute('data-journal'));
      });
    }

    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise().catch(function () {});
    }
  }

  // ---- List Detail ----

  function openListDetail(genre) {
    var label = genre.charAt(0).toUpperCase() + genre.slice(1);
    var container = document.getElementById('list-detail-content');
    var allItems = [];
    papers.forEach(function (p) { if (p.genre && p.genre.toLowerCase() === genre) allItems.push(p); });
    readlist.forEach(function (p) {
      if (p.genre && p.genre.toLowerCase() === genre && !allItems.find(function (x) { return x.id === p.id; }))
        allItems.push(p);
    });

    container.innerHTML =
      '<a href="#" class="back-link" id="list-back">← Back to Lists</a>' +
      '<h2>' + escapeHtml(label) + '</h2>' +
      '<p style="color:#9ab;margin-bottom:20px;font-size:.9rem">' + allItems.length + ' paper' + (allItems.length !== 1 ? 's' : '') + '</p>' +
      '<div class="poster-grid" id="list-detail-grid"></div>';

    var grid = document.getElementById('list-detail-grid');
    allItems.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
    });

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-list-detail').classList.add('active');
    subpageNav.style.display = 'block';
    window.scrollTo(0, 0);
    if (!restoring) {
      history.pushState({ page: 'list', genre: genre }, '', '#list/' + encodeURIComponent(genre));
    }

    document.getElementById('list-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });
  }

  // ---- Rating Detail (from histogram click) ----

  function openRatingDetail(rating) {
    var container = document.getElementById('rating-detail-content');
    var matched = papers.filter(function (p) { return p.rating === rating; });
    var label = rating + '★';

    container.innerHTML =
      '<a href="#" class="back-link" id="rating-back">← Back</a>' +
      '<h2>' + escapeHtml(label) + '</h2>' +
      '<p style="color:#9ab;margin-bottom:20px;font-size:.9rem">' + matched.length + ' paper' + (matched.length !== 1 ? 's' : '') + '</p>' +
      '<div class="poster-grid" id="rating-detail-grid"></div>';

    var grid = document.getElementById('rating-detail-grid');
    matched.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
    });

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-rating-detail').classList.add('active');
    subpageNav.style.display = 'block';
    window.scrollTo(0, 0);
    if (!restoring) {
      history.pushState({ page: 'rating', value: rating }, '', '#rating/' + rating);
    }

    document.getElementById('rating-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });
  }

  // ---- Author Detail (from clickable author names) ----

  function openAuthorDetail(author) {
    var container = document.getElementById('author-detail-content');
    var matched = papers.filter(function (p) {
      return p.authors && p.authors.indexOf(author) !== -1;
    });

    container.innerHTML =
      '<a href="#" class="back-link" id="author-back">&larr; Back</a>' +
      '<h2>' + escapeHtml(author) + '</h2>' +
      '<p style="color:#9ab;margin-bottom:20px;font-size:.9rem">' + matched.length + ' paper' + (matched.length !== 1 ? 's' : '') + '</p>' +
      '<div class="poster-grid" id="author-detail-grid"></div>';

    var grid = document.getElementById('author-detail-grid');
    matched.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
    });

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-author-detail').classList.add('active');
    subpageNav.style.display = 'block';
    window.scrollTo(0, 0);
    if (!restoring) {
      history.pushState({ page: 'author', name: author }, '', '#author/' + encodeURIComponent(author));
    }

    document.getElementById('author-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });
  }

  // ---- Journal Detail (from clickable journal names) ----

  function openJournalDetail(journal) {
    var container = document.getElementById('journal-detail-content');
    var matched = papers.filter(function (p) {
      return p.journal === journal;
    });

    container.innerHTML =
      '<a href="#" class="back-link" id="journal-back">&larr; Back</a>' +
      '<h2>' + escapeHtml(journal) + '</h2>' +
      '<p style="color:#9ab;margin-bottom:20px;font-size:.9rem">' + matched.length + ' paper' + (matched.length !== 1 ? 's' : '') + '</p>' +
      '<div class="poster-grid" id="journal-detail-grid"></div>';

    var grid = document.getElementById('journal-detail-grid');
    matched.forEach(function (p) {
      grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
    });

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    pnavLinks.forEach(function (l) { l.classList.remove('active'); });
    snavLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-journal-detail').classList.add('active');
    subpageNav.style.display = 'block';
    window.scrollTo(0, 0);
    if (!restoring) {
      history.pushState({ page: 'journal', name: journal }, '', '#journal/' + encodeURIComponent(journal));
    }

    document.getElementById('journal-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });
  }

  // ---- Search ----

  function initSearch() {
    var input = document.getElementById('search-input');
    var grid = document.getElementById('search-results');
    if (!input || !grid) return;
    input.addEventListener('input', function () {
      var q = this.value.toLowerCase().trim();
      grid.innerHTML = '';
      if (!q) return;
      var all = papers.concat(readlist);
      var seen = {};
      var results = [];
      all.forEach(function (p) {
        if (seen[p.id]) return;
        var haystack = (p.title + ' ' + (p.authors || []).join(' ') + ' ' + (p.journal || '') + ' ' + (p.genre || '')).toLowerCase();
        if (haystack.indexOf(q) !== -1) {
          seen[p.id] = true;
          results.push(p);
        }
      });
      results.forEach(function (p) {
        grid.appendChild(makePosterCard(p, { showStars: true, noHover: false }));
      });
    });
  }

  // ---- Stats Page (top 10 journals, top 10 authors) ----

  function renderStatsPage() {
    // Top journals
    var journalCounts = {};
    papers.forEach(function (p) {
      if (!p.journal) return;
      journalCounts[p.journal] = (journalCounts[p.journal] || 0) + 1;
    });
    var topJournals = Object.keys(journalCounts).map(function (j) {
      return { name: j, count: journalCounts[j] };
    }).sort(function (a, b) { return b.count - a.count; }).slice(0, 10);

    var jContainer = document.getElementById('stats-journals');
    jContainer.innerHTML = '';
    var jMax = topJournals.length > 0 ? topJournals[0].count : 1;
    topJournals.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'stats-bar-row';
      row.innerHTML =
        '<span class="stats-bar-label">' + escapeHtml(item.name) + '</span>' +
        '<div class="stats-bar-track"><div class="stats-bar-fill" style="width:' + Math.round((item.count / jMax) * 100) + '%"></div></div>' +
        '<span class="stats-bar-count">' + item.count + '</span>';
      row.style.cursor = 'pointer';
      row.addEventListener('click', (function (name) {
        return function () { openJournalDetail(name); };
      })(item.name));
      jContainer.appendChild(row);
    });

    // Top authors
    var authorCounts = {};
    papers.forEach(function (p) {
      if (!p.authors) return;
      p.authors.forEach(function (a) {
        authorCounts[a] = (authorCounts[a] || 0) + 1;
      });
    });
    var topAuthors = Object.keys(authorCounts).map(function (a) {
      return { name: a, count: authorCounts[a] };
    }).sort(function (a, b) { return b.count - a.count; }).slice(0, 10);

    var aContainer = document.getElementById('stats-authors');
    aContainer.innerHTML = '';
    var aMax = topAuthors.length > 0 ? topAuthors[0].count : 1;
    topAuthors.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'stats-bar-row';
      row.innerHTML =
        '<span class="stats-bar-label">' + escapeHtml(item.name) + '</span>' +
        '<div class="stats-bar-track"><div class="stats-bar-fill" style="width:' + Math.round((item.count / aMax) * 100) + '%"></div></div>' +
        '<span class="stats-bar-count">' + item.count + '</span>';
      row.style.cursor = 'pointer';
      row.addEventListener('click', (function (name) {
        return function () { openAuthorDetail(name); };
      })(item.name));
      aContainer.appendChild(row);
    });
  }

  // ---- Sidebar library (previously uploaded PDFs) ----

  function renderSidebarLibrary() {
    if (!window.refereedGetAllPDFs) return;
    window.refereedGetAllPDFs().then(function (items) {
      var list = document.getElementById('sidebar-library-list');
      if (!list) return;
      list.innerHTML = '';
      items.slice(0, 3).forEach(function (item) {
        var row = document.createElement('div');
        row.className = 'library-item-mini';
        row.innerHTML =
          '<span class="library-item-mini-name">' + escapeHtml(item.name) + '</span>' +
          '<span class="library-item-mini-del" data-name="' + escapeHtml(item.name) + '">✕</span>';
        row.querySelector('.library-item-mini-name').addEventListener('click', function () {
          if (window.refereedReaderOpenByName) window.refereedReaderOpenByName(item.name);
          showPage('reader');
          history.pushState({ page: 'reader' }, '', '#reader');
        });
        row.querySelector('.library-item-mini-del').addEventListener('click', function (e) {
          e.stopPropagation();
          if (window.refereedDeletePDF) {
            window.refereedDeletePDF(item.name).then(function () { renderSidebarLibrary(); });
          }
        });
        list.appendChild(row);
      });
    }).catch(function () {});
  }

  // Expose for reader to call after DB init
  window.refereedRenderSidebarLibrary = renderSidebarLibrary;

  // ---- Init ----

  function init() {
    loadData().then(function () {
      renderStats();
      renderFavorites();
      renderRecentActivity();
      renderRandomReviews();
      renderSidebarReadlist();
      renderSidebarDiary();
      renderSidebarHistogram();
      renderPapers();
      renderDiary();
      renderReadlist();
      renderLists();
      renderStatsPage();
      initSearch();

      var hash = location.hash.slice(1);
      if (hash) routeHash(hash);
    }).catch(function (err) {
      console.error('Failed to load data:', err);
    });
  }

  init();
})();
