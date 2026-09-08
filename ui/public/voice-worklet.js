/*
 * AudioWorklet processor that converts the microphone stream to 16 kHz mono
 * Int16 PCM and posts it to the main thread in chunks of 2048 samples (128 ms).
 * Resampling uses linear interpolation from the AudioContext's native rate.
 */
const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 2048;

class VoiceCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.ratio = sampleRate / TARGET_RATE;
        this.acc = new Float32Array(0);
        this.readPos = 0;
        this.out = new Int16Array(CHUNK_SAMPLES);
        this.outIdx = 0;
    }

    process(inputs) {
        const channel = inputs[0] && inputs[0][0];
        if (!channel || channel.length === 0) {
            return true;
        }

        const acc = new Float32Array(this.acc.length + channel.length);
        acc.set(this.acc);
        acc.set(channel, this.acc.length);

        let pos = this.readPos;
        while (pos + 1 < acc.length) {
            const i = Math.floor(pos);
            const frac = pos - i;
            const sample = acc[i] * (1 - frac) + acc[i + 1] * frac;
            const clamped = Math.max(-1, Math.min(1, sample));
            this.out[this.outIdx++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;

            if (this.outIdx === CHUNK_SAMPLES) {
                const buf = this.out.buffer.slice(0);
                this.port.postMessage(buf, [buf]);
                this.out = new Int16Array(CHUNK_SAMPLES);
                this.outIdx = 0;
            }
            pos += this.ratio;
        }

        const consumed = Math.floor(pos);
        this.acc = acc.slice(consumed);
        this.readPos = pos - consumed;
        return true;
    }
}

registerProcessor('voice-capture', VoiceCaptureProcessor);
