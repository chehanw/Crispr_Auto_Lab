import type { PipelineResult } from '../components/ResultsPanel';

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

// ── Load Demo (cached result, instant) ────────────────────────────────────

export async function loadDemo(
  name = 'tp53',
  signal?: AbortSignal,
): Promise<PipelineResult> {
  const res = await fetch(`${BASE}/demo/${name}`, { signal });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail; } catch { detail = await res.text().catch(() => ''); }
    throw new Error(detail || `Server returned ${res.status}`);
  }
  return res.json() as Promise<PipelineResult>;
}

// ── Run Live (streaming SSE) ───────────────────────────────────────────────

export interface StreamCallbacks {
  onStage:  (id: string, status: 'active' | 'done' | 'error') => void;
  onResult: (result: PipelineResult) => void;
  onError:  (message: string) => void;
}

export async function runLiveStream(
  hypothesis: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/run/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hypothesis }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') return;
    throw new Error('Could not reach the backend. Is the server running?');
  }

  if (!res.ok || !res.body) {
    let detail = '';
    try { detail = (await res.json()).detail; } catch { detail = await res.text().catch(() => ''); }
    throw new Error(detail || `Server returned ${res.status}`);
  }

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer    = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE messages are separated by double newlines
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith('data: ')) continue;
      try {
        const event = JSON.parse(line.slice(6));
        if (event.type === 'stage')  callbacks.onStage(event.id, event.status);
        if (event.type === 'result') callbacks.onResult(event.data);
        if (event.type === 'error')  callbacks.onError(event.message);
      } catch {
        // malformed SSE chunk — ignore
      }
    }
  }
}
