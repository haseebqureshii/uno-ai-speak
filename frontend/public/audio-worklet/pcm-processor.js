/**
 * AudioWorklet processor that converts Float32 PCM chunks from the microphone
 * into 16-bit PCM Int16Array buffers and posts them to the main thread.
 *
 * This file is loaded dynamically by useAudioRecorder.ts.
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.bufferSize = options.processorOptions?.bufferSize ?? 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.index = 0;
  }

  process(inputs, _outputs, _parameters) {
    const input = inputs[0];
    if (!input || !input.length) return true;

    const channel = input[0];
    for (let i = 0; i < channel.length; i++) {
      this.buffer[this.index++] = channel[i];
      if (this.index >= this.bufferSize) {
        this.port.postMessage(float32ToInt16(this.buffer).buffer, [
          float32ToInt16(this.buffer).buffer,
        ]);
        this.index = 0;
      }
    }
    return true;
  }
}

function float32ToInt16(input) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

registerProcessor("pcm-processor", PCMProcessor);
