/* ===================================================
   Refereed — Main Application Script
   =================================================== */

(function () {
  'use strict';

  let papers = [];
  let watchlist = [];

  // ---- Helpers ----

  function ratingToStars(r) {
    if (!r) return '';
    const full = Math.floor(r);
    const half = r % 1 >= 0.5;
    return '★'.repeat(full) + (half ? '½' : '');
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);

    // Preserve display math ($$...$$)  — use placeholder to avoid inline processing
    const displayMathBlocks = [];
    html = html.replace(/\$\$([\s\S]*?)\$\$/g, function (_, m) {
      displayMathBlocks.push(m);
      return '%%DISPLAY_MATH_' + (displayMathBlocks.length - 1) + '%%';
    });

    // Preserve inline math ($...$)
    const inlineMathBlocks = [];
    html = html.replace(/\$([^\$\n]+?)\$/g, function (_, m) {
      inlineMathBlocks.push(m);
      return '%%INLINE_MATH_' + (inlineMathBlocks.length - 1) + '%%';
    });

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Ordered lists
    html = html.replace(/^(\d+)\.\s+(.+)$/gm, '<li>$2</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, function (match) {
      return '<ol>' + match + '</ol>';
    });

    // Paragraphs
    html = html.replace(/\n{2,}/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p>\s*<\/p>/g, '');

    // Restore display math
    displayMathBlocks.forEach(function (m, i) {
      html = html.replace('%%DISPLAY_MATH_' + i + '%%', '$$' + m + '$$');
    });

    // Restore inline math
    inlineMathBlocks.forEach(function (m, i) {
      html = html.replace('%%INLINE_MATH_' + i + '%%', '$' + m + '$');
    });

    return html;
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function monthKey(iso) {
    if (!iso) return 'Unknown';
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long' });
  }

  function currentYear() {
    return new Date().getFullYear();
  }

  // ---- Navigation ----

  const navLinks = document.querySelectorAll('.nav-link');
  const pages = document.querySelectorAll('.page');

  function showPage(name) {
    pages.forEach(function (p) { p.classList.remove('active'); });
    navLinks.forEach(function (l) { l.classList.remove('active'); });
    const target = document.getElementById('page-' + name);
    if (target) target.classList.add('active');
    const link = document.querySelector('[data-page="' + name + '"]');
    if (link) link.classList.add('active');
    window.scrollTo(0, 0);

    // Typeset MathJax if present
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise().catch(function () {});
    }
  }

  navLinks.forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      var page = this.getAttribute('data-page');
      showPage(page);
      history.pushState({ page: page }, '', '#' + page);
    });
  });

  window.addEventListener('popstate', function (e) {
    if (e.state && e.state.page) {
      showPage(e.state.page);
    } else {
      var hash = location.hash.replace('#', '') || 'profile';
      showPage(hash);
    }
  });

  // ---- Data Loading ----

  function loadData() {
    return Promise.all([
      fetch('data/papers.json').then(function (r) { return r.json(); }),
      fetch('data/watchlist.json').then(function (r) { return r.json(); })
    ]).then(function (results) {
      papers = results[0];
      watchlist = results[1];
    });
  }

  // ---- Rendering ----

  function renderStats() {
    document.getElementById('stat-total').textContent = papers.length;
    var thisYear = papers.filter(function (p) {
      return p.date_read && p.date_read.startsWith(String(currentYear()));
    }).length;
    document.getElementById('stat-year').textContent = thisYear;
    document.getElementById('stat-watchlist').textContent = watchlist.length;
    var genres = new Set();
    papers.forEach(function (p) { if (p.genre) genres.add(p.genre); });
    watchlist.forEach(function (p) { if (p.genre) genres.add(p.genre); });
    document.getElementById('stat-genres').textContent = genres.size;
  }

  function renderFavorites() {
    var grid = document.getElementById('favorites-grid');
    grid.innerHTML = '';
    papers.filter(function (p) { return p.favorite; }).forEach(function (p) {
      grid.appendChild(createPosterCard(p, true));
    });
  }

  function renderRecentActivity() {
    var container = document.getElementById('recent-activity');
    container.innerHTML = '';
    var sorted = papers.slice().sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    sorted.slice(0, 5).forEach(function (p) {
      var item = document.createElement('div');
      item.className = 'activity-item';
      item.innerHTML =
        '<div class="activity-poster"><img src="' + escapeHtml(p.poster) + '" alt="" loading="lazy"></div>' +
        '<div class="activity-text">' +
          '<p><strong>' + escapeHtml(p.title) + '</strong> (' + p.year + ') — ' +
          '<span class="stars">' + ratingToStars(p.rating) + '</span></p>' +
          '<div class="activity-date">' + formatDate(p.date_read) + '</div>' +
        '</div>';
      item.style.cursor = 'pointer';
      item.addEventListener('click', function () { openReview(p.id); });
      container.appendChild(item);
    });
  }

  function renderActivity() {
    var container = document.getElementById('activity-feed');
    container.innerHTML = '';
    var sorted = papers.slice().sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    sorted.forEach(function (p) {
      var item = document.createElement('div');
      item.className = 'activity-item';
      item.innerHTML =
        '<div class="activity-poster"><img src="' + escapeHtml(p.poster) + '" alt="" loading="lazy"></div>' +
        '<div class="activity-text">' +
          '<p><strong>' + escapeHtml(p.title) + '</strong> (' + p.year + ') — ' +
          '<span class="stars">' + ratingToStars(p.rating) + '</span>' +
          (p.favorite ? ' <span style="color:#ff5050">♥</span>' : '') + '</p>' +
          '<p style="font-size:0.8rem;color:#9ab">' + escapeHtml(p.authors.join(', ')) + '</p>' +
          '<div class="activity-date">' + formatDate(p.date_read) + '</div>' +
        '</div>';
      item.style.cursor = 'pointer';
      item.addEventListener('click', function () { openReview(p.id); });
      container.appendChild(item);
    });
  }

  function createPosterCard(p, showRating) {
    var card = document.createElement('div');
    card.className = 'poster-card';
    var overlay = '';
    if (showRating) {
      overlay = '<div class="poster-overlay">' +
        '<div class="poster-title">' + escapeHtml(p.title) + '</div>' +
        (p.rating ? '<div class="poster-rating">' + ratingToStars(p.rating) + '</div>' : '') +
        '</div>';
    }
    card.innerHTML = '<img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' + overlay;
    card.addEventListener('click', function () {
      if (p.review) {
        openReview(p.id);
      }
    });
    return card;
  }

  function renderPapers() {
    var grid = document.getElementById('papers-grid');
    grid.innerHTML = '';
    papers.forEach(function (p) {
      grid.appendChild(createPosterCard(p, true));
    });
  }

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
      var section = document.createElement('div');
      section.className = 'diary-month';
      section.innerHTML = '<h3>' + mk + '</h3>';
      groups[mk].forEach(function (p) {
        var entry = document.createElement('div');
        entry.className = 'diary-entry';
        entry.innerHTML =
          '<div class="diary-entry-poster"><img src="' + escapeHtml(p.poster) + '" alt="" loading="lazy"></div>' +
          '<div class="diary-entry-info">' +
            '<div class="diary-entry-title">' + escapeHtml(p.title) + '</div>' +
            '<div class="diary-entry-meta">' +
              '<span class="diary-entry-rating stars">' + ratingToStars(p.rating) + '</span>' +
              (p.favorite ? ' <span style="color:#ff5050">♥</span>' : '') +
            '</div>' +
          '</div>' +
          '<div class="diary-entry-date">' + formatDate(p.date_read) + '</div>';
        entry.addEventListener('click', function () { openReview(p.id); });
        section.appendChild(entry);
      });
      container.appendChild(section);
    });
  }

  function renderReviews() {
    var container = document.getElementById('reviews-list');
    container.innerHTML = '';
    var sorted = papers.slice().filter(function (p) {
      return p.review;
    }).sort(function (a, b) {
      return (b.date_read || '').localeCompare(a.date_read || '');
    });
    sorted.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'review-card';
      var excerpt = p.review.substring(0, 250).replace(/\$[^$]*\$/g, '[math]');
      card.innerHTML =
        '<div class="review-card-header">' +
          '<div class="review-card-poster"><img src="' + escapeHtml(p.poster) + '" alt="" loading="lazy"></div>' +
          '<div class="review-card-info">' +
            '<div class="review-card-title">' + escapeHtml(p.title) + '</div>' +
            '<div class="review-card-meta">' + p.year + ' · ' + escapeHtml(p.authors.join(', ')) + '</div>' +
            '<div class="review-card-rating stars">' + ratingToStars(p.rating) +
              (p.favorite ? ' <span style="color:#ff5050">♥</span>' : '') +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="review-card-excerpt">' + escapeHtml(excerpt) + '…</div>';
      card.addEventListener('click', function () { openReview(p.id); });
      container.appendChild(card);
    });
  }

  function renderWatchlist() {
    var grid = document.getElementById('watchlist-grid');
    grid.innerHTML = '';
    watchlist.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'poster-card';
      card.innerHTML =
        '<img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' +
        '<div class="poster-overlay">' +
          '<div class="poster-title">' + escapeHtml(p.title) + '</div>' +
          '<div style="font-size:0.7rem;color:#9ab">' + p.year + '</div>' +
        '</div>';
      grid.appendChild(card);
    });
  }

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
    watchlist.forEach(function (p) {
      if (!p.genre) return;
      var g = p.genre.toLowerCase();
      if (!genreMap[g]) genreMap[g] = [];
      // avoid duplicate
      if (!genreMap[g].find(function (x) { return x.id === p.id; })) {
        genreMap[g].push(p);
      }
    });
    Object.keys(genreMap).sort().forEach(function (genre) {
      var items = genreMap[genre];
      var card = document.createElement('div');
      card.className = 'list-card';
      var postersHtml = items.slice(0, 4).map(function (p) {
        return '<div class="mini-poster"><img src="' + escapeHtml(p.poster) + '" alt="" loading="lazy"></div>';
      }).join('');
      var label = genre.charAt(0).toUpperCase() + genre.slice(1);
      card.innerHTML =
        '<div class="list-card-posters">' + postersHtml + '</div>' +
        '<div class="list-card-info">' +
          '<h3>' + escapeHtml(label) + '</h3>' +
          '<p>' + items.length + ' paper' + (items.length !== 1 ? 's' : '') + '</p>' +
        '</div>';
      card.addEventListener('click', function () { openListDetail(genre); });
      container.appendChild(card);
    });
  }

  // ---- Detail Views ----

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
            '<div class="review-detail-authors">' + escapeHtml(p.authors.join(', ')) + '</div>' +
            '<div class="review-detail-genre">' + escapeHtml(p.genre || '') + '</div>' +
            '<div class="review-detail-rating stars">' + ratingToStars(p.rating) + '</div>' +
            (p.favorite ? '<div class="review-detail-favorite">♥ Favorite</div>' : '') +
            '<div class="review-detail-date">Read ' + formatDate(p.date_read) + '</div>' +
            (p.pdf ? '<div style="margin-top:8px"><a href="' + escapeHtml(p.pdf) + '" target="_blank" rel="noopener noreferrer" style="font-size:0.85rem">View PDF →</a></div>' : '') +
          '</div>' +
        '</div>' +
        '<div class="review-detail-body">' + renderMarkdown(p.review) + '</div>' +
      '</div>';

    // Show page
    pages.forEach(function (pg) { pg.classList.remove('active'); });
    navLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-review-detail').classList.add('active');
    window.scrollTo(0, 0);

    document.getElementById('review-back').addEventListener('click', function (e) {
      e.preventDefault();
      history.back();
    });

    // MathJax typeset
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise().catch(function () {});
    }
  }

  function openListDetail(genre) {
    var label = genre.charAt(0).toUpperCase() + genre.slice(1);
    var container = document.getElementById('list-detail-content');

    var allItems = [];
    papers.forEach(function (p) {
      if (p.genre && p.genre.toLowerCase() === genre) allItems.push(p);
    });
    watchlist.forEach(function (p) {
      if (p.genre && p.genre.toLowerCase() === genre) {
        if (!allItems.find(function (x) { return x.id === p.id; })) {
          allItems.push(p);
        }
      }
    });

    var gridHtml = '';
    allItems.forEach(function (p) {
      gridHtml +=
        '<div class="poster-card" data-id="' + escapeHtml(p.id) + '">' +
          '<img src="' + escapeHtml(p.poster) + '" alt="' + escapeHtml(p.title) + '" loading="lazy">' +
          '<div class="poster-overlay">' +
            '<div class="poster-title">' + escapeHtml(p.title) + '</div>' +
            (p.rating ? '<div class="poster-rating">' + ratingToStars(p.rating) + '</div>' : '') +
          '</div>' +
        '</div>';
    });

    container.innerHTML =
      '<a href="#" class="back-link" id="list-back">← Back to Lists</a>' +
      '<h2>' + escapeHtml(label) + '</h2>' +
      '<p style="color:#9ab;margin-bottom:20px;font-size:0.9rem">' + allItems.length + ' paper' + (allItems.length !== 1 ? 's' : '') + '</p>' +
      '<div class="poster-grid">' + gridHtml + '</div>';

    // Attach click handlers
    container.querySelectorAll('.poster-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var pid = this.getAttribute('data-id');
        var found = papers.find(function (x) { return x.id === pid; });
        if (found && found.review) openReview(pid);
      });
    });

    pages.forEach(function (pg) { pg.classList.remove('active'); });
    navLinks.forEach(function (l) { l.classList.remove('active'); });
    document.getElementById('page-list-detail').classList.add('active');
    window.scrollTo(0, 0);

    document.getElementById('list-back').addEventListener('click', function (e) {
      e.preventDefault();
      showPage('lists');
    });
  }

  // ---- Init ----

  function init() {
    loadData().then(function () {
      renderStats();
      renderFavorites();
      renderRecentActivity();
      renderActivity();
      renderPapers();
      renderDiary();
      renderReviews();
      renderWatchlist();
      renderLists();

      // Handle initial hash
      var hash = location.hash.replace('#', '');
      if (hash) {
        showPage(hash);
      }
    }).catch(function (err) {
      console.error('Failed to load data:', err);
    });
  }

  init();
})();
