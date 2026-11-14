/* The file view only discovers a port and navigates. The connected page owns API commands. */
window.findBeatOSConnection = async function findBeatOSConnection(hint) {
  if (!hint || !Number.isInteger(hint.port) || hint.port < 1 || hint.port > 65535 ||
      !/^[a-f0-9]{64}$/.test(hint.key)) return null;
  const base = 'http://127.0.0.1:' + hint.port;
  return new Promise(resolve => {
    const script = document.createElement('script');
    const finish = () => {
      clearTimeout(timer);
      script.remove();
      resolve(window.beatosProbeKey === hint.key && window.__BEATOS_LOCAL_SERVER_ONLINE === base ? base : null);
    };
    const timer = setTimeout(finish, 2500);
    window.beatosProbeKey = '';
    window.__BEATOS_LOCAL_SERVER_ONLINE = '';
    script.src = base + '/beatos-online.js?t=' + Date.now();
    script.onload = script.onerror = finish;
    document.head.append(script);
  });
};

window.readBeatOSConnection = async function readBeatOSConnection(path) {
  const hint = await new Promise(resolve => {
    const script = document.createElement('script');
    const finish = () => {
      clearTimeout(timer);
      script.remove();
      resolve(window.beatosConnection);
    };
    const timer = setTimeout(finish, 1500);
    window.beatosConnection = null;
    script.src = path + '?t=' + Date.now();
    script.onload = script.onerror = finish;
    document.head.append(script);
  });
  return window.findBeatOSConnection(hint);
};
