// A keyed debouncer: many events for one key become one call after a quiet period.
// Why: a save, a format-on-save and a file watcher can all fire for one edit; the check should run once.

export class Debouncer {
  private timers = new Map<string, ReturnType<typeof setTimeout>>();

  /** Run `action` after `delayMs` with no further call for `key`; a newer call for the same key replaces it. */
  schedule(key: string, delayMs: number, action: () => void): void {
    const old = this.timers.get(key);
    if (old) { clearTimeout(old); }
    this.timers.set(key, setTimeout(() => { this.timers.delete(key); action(); }, delayMs));
  }

  /** Cancel everything pending (on deactivate). */
  dispose(): void {
    for (const t of this.timers.values()) { clearTimeout(t); }
    this.timers.clear();
  }
}
