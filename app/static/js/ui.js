/**
 * Daboji Auto Clipper — UI Cinema Helper
 * Ringan, tanpa dependensi eksternal, aman jika elemen tidak ada.
 */
(function () {
  'use strict';

  function updateNavScroll() {
    const nav = document.getElementById('main-nav') || document.querySelector('.navbar');
    if (nav) {
      nav.classList.toggle('solid', window.scrollY > 20);
    }
  }

  function updateActiveNavLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link, .nav li a');
    navLinks.forEach((link) => {
      const href = link.getAttribute('href');
      if (!href) return;
      let isActive = false;
      if (href === '/' || href === '') {
        isActive = currentPath === '/';
      } else if (href.startsWith('/')) {
        isActive = currentPath === href || currentPath.startsWith(href + '/');
      }
      link.classList.toggle('active', isActive);
      if (isActive) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  function initRowScrollers() {
    document.querySelectorAll('.row-wrap').forEach((wrap) => {
      const row = wrap.querySelector('.row-scroller') || wrap.querySelector('.row');
      if (!row) return;
      wrap.querySelectorAll('.arrow').forEach((arrow) => {
        if (arrow.dataset.boundScroll) return;
        arrow.dataset.boundScroll = '1';
        arrow.addEventListener('click', (e) => {
          e.preventDefault();
          const dir = parseFloat(arrow.dataset.d || '1');
          const scrollAmount = row.clientWidth * 0.75 * dir;
          row.scrollBy({ left: scrollAmount, behavior: 'smooth' });
        });
      });
    });
  }

  let lastStatusFetchTime = 0;
  const STATUS_FETCH_THROTTLE_MS = 60000;

  async function updateNavbarPlatformStatus(force = false) {
    const now = Date.now();
    if (!force && (now - lastStatusFetchTime < STATUS_FETCH_THROTTLE_MS)) {
      return;
    }
    lastStatusFetchTime = now;

    const pillIg = document.getElementById('pill-ig-status');
    const pillTikTok = document.getElementById('pill-tiktok-status');

    if (pillIg) {
      try {
        const res = await fetch('/instagram/status');
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'active') {
            const days = data.days_left != null ? data.days_left : '?';
            if (data.days_left != null && data.days_left <= 7) {
              pillIg.className = 'pill';
              pillIg.innerHTML = `<span class="dot warn"></span>Instagram · ${days}h`;
              pillIg.title = `Instagram aktif (token habis dalam ${days} hari)`;
              pillIg.style.display = 'inline-flex';
            } else {
              pillIg.className = 'pill';
              pillIg.innerHTML = `<span class="dot"></span>Instagram · ${days} hari`;
              pillIg.title = `Instagram terhubung (${days} hari)`;
              pillIg.style.display = 'inline-flex';
            }
          } else if (data.status === 'needs_reconnect') {
            pillIg.className = 'pill';
            pillIg.innerHTML = `<span class="dot warn"></span>Instagram !`;
            pillIg.title = 'Instagram perlu reconnect token';
            pillIg.style.display = 'inline-flex';
          } else if (data.status === 'not_configured') {
            pillIg.className = 'pill';
            pillIg.innerHTML = `<i class="bi bi-instagram me-1"></i>Instagram`;
            pillIg.title = 'Instagram belum dikonfigurasi';
            pillIg.style.display = 'inline-flex';
          } else {
            pillIg.style.display = 'none';
          }
        } else {
          pillIg.style.display = 'none';
        }
      } catch {
        pillIg.style.display = 'none';
      }
    }

    if (pillTikTok) {
      try {
        const res = await fetch('/tiktok/status');
        if (res.ok) {
          const data = await res.json();
          if (data.connected) {
            pillTikTok.className = 'pill';
            pillTikTok.innerHTML = `<span class="dot"></span>TikTok`;
            pillTikTok.title = 'TikTok terhubung (buka Settings)';
            pillTikTok.style.display = 'inline-flex';
            pillTikTok.style.cursor = 'pointer';
            pillTikTok.onclick = () => { window.location.href = '/settings'; };
          } else {
            pillTikTok.className = 'pill';
            pillTikTok.innerHTML = `<i class="bi bi-tiktok me-1"></i>TikTok`;
            pillTikTok.title = 'TikTok belum terhubung (buka Settings)';
            pillTikTok.style.display = 'inline-flex';
            pillTikTok.style.cursor = 'pointer';
            pillTikTok.onclick = () => { window.location.href = '/settings'; };
          }
        } else {
          pillTikTok.style.display = 'none';
        }
      } catch {
        pillTikTok.style.display = 'none';
      }
    }
  }

  function initUI() {
    updateNavScroll();
    updateActiveNavLink();
    initRowScrollers();
    updateNavbarPlatformStatus(false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUI);
  } else {
    initUI();
  }

  // Handle click on candidate preview thumbnails or play button
  document.addEventListener('click', (e) => {
    const thumb = e.target.closest('.thumb');
    if (!thumb) return;

    // Don't intercept clicks on links or non-play buttons
    if (e.target.closest('a, button')) return;

    const video = thumb.querySelector('video');
    if (!video) return;

    // If clicked directly on the video element's bottom area (native controls), let native controls handle it
    if (e.target === video) {
      const rect = video.getBoundingClientRect();
      const clickY = e.clientY - rect.top;
      if (clickY > rect.height - 42) {
        return;
      }
    }

    e.preventDefault();
    e.stopPropagation();

    if (video.paused) {
      // Pause any other playing video previews on the page
      document.querySelectorAll('.thumb video').forEach((v) => {
        if (v !== video && !v.paused) v.pause();
      });
      video.play().catch((err) => {
        console.warn('[Video Player] Failed to play video with audio, retrying muted...', err);
        // Fallback: if browser blocks autoplay due to sound policy
        video.muted = true;
        video.play().catch((e2) => {
          console.error('[Video Player] Playback failed completely:', e2);
        });
      });
    } else {
      video.pause();
    }
  });

  // Sync play/pause icons and classes
  document.addEventListener('play', (e) => {
    if (e.target && e.target.tagName && e.target.tagName.toLowerCase() === 'video') {
      const thumb = e.target.closest('.thumb');
      if (thumb) {
        thumb.classList.add('is-playing');
        const b = thumb.querySelector('.play b');
        if (b) b.textContent = '❚❚';
      }
    }
  }, true);

  document.addEventListener('pause', (e) => {
    if (e.target && e.target.tagName && e.target.tagName.toLowerCase() === 'video') {
      const thumb = e.target.closest('.thumb');
      if (thumb) {
        thumb.classList.remove('is-playing');
        const b = thumb.querySelector('.play b');
        if (b) b.textContent = '▶';
      }
    }
  }, true);

  document.addEventListener('ended', (e) => {
    if (e.target && e.target.tagName && e.target.tagName.toLowerCase() === 'video') {
      const thumb = e.target.closest('.thumb');
      if (thumb) {
        thumb.classList.remove('is-playing');
        const b = thumb.querySelector('.play b');
        if (b) b.textContent = '▶';
      }
    }
  }, true);

  window.addEventListener('scroll', updateNavScroll, { passive: true });
  document.addEventListener('htmx:pushedIntoHistory', updateActiveNavLink);
  document.addEventListener('htmx:afterSettle', initUI);
})();
