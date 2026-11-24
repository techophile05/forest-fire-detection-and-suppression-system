(function () {
  'use strict';

  var chips = document.querySelectorAll('[data-live-status]');
  if (!chips.length) return;

  var API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8080' : '';
  var POLL_MS = 5000;

  function apply(label, level) {
    chips.forEach(function (chip) {
      chip.textContent = label;
      chip.setAttribute('data-level', level);
      chip.setAttribute('title', 'ESP status: ' + label.toLowerCase());
    });
  }

  function poll() {
    fetch(API_BASE + '/api/health', { cache: 'no-store' })
      .then(function (res) { return res.json(); })
      .then(function (health) {
        var esp = health.esp || {};
        if (!esp.reachable) apply('ESP Offline', 'crit');
        else if (esp.stale) apply('Stale Data', 'warn');
        else apply('ESP Online', 'safe');
      })
      .catch(function () { apply('Backend Offline', 'crit'); });
  }

  apply('Connecting…', 'pending');
  poll();
  setInterval(poll, POLL_MS);
})();
