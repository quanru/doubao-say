import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { ComputerDevice } from '@midscene/computer';

const run = promisify(execFile);

// screenshot-desktop can miss the hosted virtual display in system_profiler.
// Capture the real primary display with the system tool in that specific case.
export class MacComputerDevice extends ComputerDevice {
  override async screenshotBase64(): Promise<string> {
    try { return await super.screenshotBase64(); }
    catch (error) {
      if (process.platform !== 'darwin' || process.env.MIDSCENE_MACOS_DISPLAY_ID ||
          !(error instanceof Error) || !error.message.includes('No displays detected')) throw error;
      const directory = await mkdtemp(join(tmpdir(), 'doubao-midscene-screen-'));
      try {
        const path = join(directory, 'primary.png');
        await run('/usr/sbin/screencapture', ['-x', '-D', '1', '-t', 'png', path], { timeout: 10_000 });
        const data = await readFile(path);
        if (!data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
          throw new Error('Native display capture did not produce a PNG');
        }
        return `data:image/png;base64,${data.toString('base64')}`;
      } finally { await rm(directory, { recursive: true, force: true }); }
    }
  }
}
