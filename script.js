// Forest Fire Detection System — live backend client only
(function () {
    const API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8080' : '';

    function $(id) {
        return document.getElementById(id);
    }

    function setText(id, value) {
        const el = $(id);
        if (el) el.textContent = value;
    }

    async function poll() {
        const lastUpdate = $('lastUpdate');
        const uptime = $('uptime');
        const temperature = $('temperature');
        const humidity = $('humidity');
        const gas = $('gas');
        if (!lastUpdate && !temperature) {
            return;
        }

        try {
            const response = await fetch(API_BASE + '/api/data', { cache: 'no-store' });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const data = await response.json();
            const sensors = data.sensors || {};
            const esp = data.esp || {};

            let status = 'ESP ONLINE';
            if (!esp.reachable) status = 'ESP OFFLINE';
            else if (esp.stale) status = 'STALE DATA';

            setText('nodeStatusText', status);
            setText('lastUpdate', data.last_successful_reading
                ? new Date(data.last_successful_reading).toLocaleString()
                : '—');
            setText('temperature', sensors.temperature == null ? 'N/A' : sensors.temperature + '°C');
            setText('humidity', sensors.humidity == null ? 'N/A' : sensors.humidity + '%');
            setText('pressure', sensors.pressure == null ? 'N/A' : sensors.pressure + ' hPa');
            setText('gas', (sensors.mq4 == null && sensors.gas == null) ? 'N/A' : (sensors.mq4 != null ? sensors.mq4 : sensors.gas) + ' ppm');
            if (uptime && data.esp && data.esp.uptime_ms != null) {
                const seconds = Math.floor(Number(data.esp.uptime_ms) / 1000);
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                const secs = seconds % 60;
                uptime.textContent =
                    String(hours).padStart(2, '0') + ':' +
                    String(minutes).padStart(2, '0') + ':' +
                    String(secs).padStart(2, '0');
            }
        } catch (err) {
            setText('nodeStatusText', 'ESP OFFLINE');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const deployForm = document.querySelector('.deploy-form');
        if (deployForm) {
            deployForm.addEventListener('submit', function (e) {
                e.preventDefault();
                if (!confirm('Deploy fire suppression? This sends POST /api/deploy. It is not automatic.')) {
                    return;
                }
                fetch(API_BASE + '/api/deploy', { method: 'POST' })
                    .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
                    .then(function (res) {
                        alert(res.ok && res.j.status === 'success' ? ('Success: ' + res.j.message) : ('Failure: ' + (res.j.message || 'deploy failed')));
                    })
                    .catch(function (err) {
                        alert('Offline: ' + err.message);
                    });
            });
        }
        poll();
        setInterval(poll, 2000);
    });
})();
