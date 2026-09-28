import { deflateSync } from 'node:zlib';
const crc = (bytes) => {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let i = 0; i < 8; i++) value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
};
const chunk = (type, payload) => {
  const name = Buffer.from(type);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(payload.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc(Buffer.concat([name, payload])));
  return Buffer.concat([length, name, payload, checksum]);
};
const width = 96;
const height = 48;
const header = Buffer.alloc(13);
header.writeUInt32BE(width, 0);
header.writeUInt32BE(height, 4);
header.set([8, 2], 8);
const pixels = Buffer.alloc(height * (1 + width * 3));
for (let y = 0; y < height; y++) {
  for (let x = 0; x < width; x++) {
    const offset = y * (1 + width * 3) + 1 + x * 3;
    pixels.set(x < width / 2 ? [255, 0, 0] : [0, 0, 255], offset);
  }
}
const png = Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header),
  chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
const image = `data:image/png;base64,${png.toString('base64')}`;
const models = ['deepseek-v4-1-flash-260910', 'doubao-seed-2-0-lite-260428', 'doubao-seed-2-1-turbo-260628'];
let success = false;
for (const model of models) {
  const response = await fetch(`${process.env.MODEL_BASE_URL.replace(/\/+$/, '')}/chat/completions`, {
    method: 'POST', headers: { authorization: `Bearer ${process.env.MODEL_API_KEY}`,
      'content-type': 'application/json' },
    body: JSON.stringify({ model, max_tokens: 100, messages: [{ role: 'user', content: [
      { type: 'text', text: 'What are the colors of the left and right halves of this image? Answer in two words.' },
      { type: 'image_url', image_url: { url: image } },
    ] }] }), signal: AbortSignal.timeout(40_000),
  });
  const data = await response.json().catch(() => ({}));
  const answer = String(data.choices?.[0]?.message?.content || '').trim().slice(0, 100);
  const verified = response.ok && /red/i.test(answer) && /blue/i.test(answer);
  console.log(`${model}: HTTP ${response.status}, image understood: ${verified}, answer: ${answer}`);
  if (verified) success = true;
}
if (!success) throw new Error('No configured hosted model could understand the test image');
