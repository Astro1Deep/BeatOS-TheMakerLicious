// PCM capture only: no monitoring, channel mixing, gain or audio effects.
class PO33Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(8192);
    this.used = 0;
    this.stopped = false;
    this.port.onmessage = ({data}) => {
      if (data === 'stop' && !this.stopped) {
        this.flush();
        this.stopped = true;
        this.port.postMessage({stopped: true});
      }
    };
  }
  flush() {
    if (this.used) {
      const pcm = this.buffer.slice(0, this.used);
      this.port.postMessage({pcm: pcm.buffer}, [pcm.buffer]);
      this.used = 0;
    }
  }
  process(inputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels || !channels.length) return true;
    if (channels.length !== 2) {
      this.stopped = true;
      this.port.postMessage({error: 'La entrada no entrega dos canales. Selecciona una entrada de línea estéreo.'});
      return false;
    }
    for (let frame = 0; frame < channels[0].length; frame++) {
      for (let channel = 0; channel < 2; channel++) {
        const value = Math.max(-1, Math.min(1, channels[channel][frame]));
        this.buffer[this.used++] = Math.round(value * (value < 0 ? 32768 : 32767));
      }
      if (this.used === this.buffer.length) this.flush();
    }
    return true;
  }
}
registerProcessor('po33-capture', PO33Capture);
