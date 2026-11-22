// PCM capture + live L/R meter telemetry: no audio monitoring, channel mixing, gain or FX.
class PO33Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(8192);
    this.used = 0;
    this.stopped = false;
    this.monitorOnly = false;
    this.enableMeter = false;
    this.chL = 0;
    this.chR = 1;
    this.meterFrames = 0;
    this.mPeakL = 0;
    this.mPeakR = 0;
    this.mSqL = 0;
    this.mSqR = 0;
    this.mDiff = 0;
    this.mAbs = 0;
    this.mClip = false;
    this.port.onmessage = ({data}) => {
      if (data === 'stop' && !this.stopped) {
        if (this.enableMeter && this.meterFrames > 0) this.flushMeter(2);
        this.flush();
        this.stopped = true;
        this.port.postMessage({stopped: true});
      } else if (data && typeof data === 'object' && data.cmd === 'config') {
        if (typeof data.monitorOnly === 'boolean') this.monitorOnly = data.monitorOnly;
        if (typeof data.enableMeter === 'boolean') this.enableMeter = data.enableMeter;
        if (Number.isInteger(data.chL) && data.chL >= 0) this.chL = data.chL;
        if (Number.isInteger(data.chR) && data.chR >= 0) this.chR = data.chR;
      }
    };
  }
  flushMeter(channelCount) {
    const n = Math.max(1, this.meterFrames);
    this.port.postMessage({
      meter: {
        peakL: this.mPeakL,
        peakR: this.mPeakR,
        rmsL: Math.sqrt(this.mSqL / n),
        rmsR: Math.sqrt(this.mSqR / n),
        stereoRatio: this.mAbs > 1e-6 ? this.mDiff / this.mAbs : 0,
        clipped: this.mClip,
        channelCount: channelCount || 2,
      }
    });
    this.meterFrames = 0;
    this.mPeakL = 0;
    this.mPeakR = 0;
    this.mSqL = 0;
    this.mSqR = 0;
    this.mDiff = 0;
    this.mAbs = 0;
    this.mClip = false;
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
    if (channels.length < 2 || this.chL >= channels.length || this.chR >= channels.length) {
      this.stopped = true;
      this.port.postMessage({error: 'La entrada no entrega dos canales. Selecciona una entrada de línea estéreo.'});
      return false;
    }
    const left = channels[this.chL];
    const right = channels[this.chR];
    for (let frame = 0; frame < left.length; frame++) {
      const lv = Math.max(-1, Math.min(1, left[frame]));
      const rv = Math.max(-1, Math.min(1, right[frame]));
      if (!this.monitorOnly) {
        this.buffer[this.used++] = Math.round(lv * (lv < 0 ? 32768 : 32767));
        this.buffer[this.used++] = Math.round(rv * (rv < 0 ? 32768 : 32767));
        if (this.used === this.buffer.length) this.flush();
      }
      if (this.enableMeter) {
        const al = Math.abs(lv), ar = Math.abs(rv);
        if (al > this.mPeakL) this.mPeakL = al;
        if (ar > this.mPeakR) this.mPeakR = ar;
        this.mSqL += lv * lv;
        this.mSqR += rv * rv;
        this.mDiff += Math.abs(lv - rv);
        this.mAbs += al + ar;
        if (al >= 0.995 || ar >= 0.995) this.mClip = true;
        this.meterFrames++;
      }
    }
    if (this.enableMeter && this.meterFrames >= 2048) {
      this.flushMeter(channels.length);
    }
    return true;
  }
}
registerProcessor('po33-capture', PO33Capture);
