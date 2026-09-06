/** Older overlapping refreshes resolve to the newest read, never stale rows. */
export async function readLatest<T>(read: Promise<T>, latest: { current: Promise<T> | null }): Promise<T> {
  latest.current = read;
  let pending = read;
  for (;;) {
    try {
      const value = await pending;
      if (latest.current === pending) return value;
    } catch (error) {
      if (latest.current === pending) throw error;
    }
    pending = latest.current!;
  }
}
