import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { parseCliArgs, runNonInteractive } from "./setup.js";
import type { MoltbotPluginAPI, ServiceConfig } from "./types.js";
import { isVendorHosted } from "./vendor-host.js";

const daemon = vi.hoisted(() => ({ constructed: 0 }));
vi.mock("@vectorize-io/hindsight-all", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@vectorize-io/hindsight-all")>();
  return {
    ...actual,
    HindsightServer: class {
      constructor() {
        daemon.constructed += 1;
      }
      async start() {}
      async stop() {}
      async checkHealth() {
        return false;
      }
      getBaseUrl() {
        return "http://127.0.0.1:9077";
      }
    },
  };
});

const HOSTED = "https://api.hindsight.vectorize.io";

describe("isVendorHosted", () => {
  it.each([
    HOSTED,
    "https://vectorize.io",
    "HTTPS://UI.Hindsight.VECTORIZE.IO:443/v1",
    "https://api.hindsight.vectorize.io./",
    "https://user:pw@api.hindsight.vectorize.io",
    "  api.hindsight.vectorize.io  ",
    "api.hindsight.vectorize.io:443",
  ])("refuses %s", (url) => {
    expect(isVendorHosted(url)).toBe(true);
  });

  it.each([
    "http://localhost:8888",
    "http://10.0.0.5:8888",
    "https://notvectorize.io",
    "https://vectorize.io.home.arpa",
    "https://home.arpa/vectorize.io",
    undefined,
  ])("keeps %s", (url) => {
    expect(isVendorHosted(url)).toBe(false);
  });
});

describe("a hindsightApiUrl on a vendor host", () => {
  let service: ServiceConfig | undefined;
  const dirs: string[] = [];

  afterEach(async () => {
    await service?.stop().catch(() => {});
    service = undefined;
    vi.unstubAllGlobals();
    vi.resetModules();
    daemon.constructed = 0;
    for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  /** Runs the real plugin start and reports what it reached. */
  const start = async (config: Record<string, unknown>) => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    const dir = mkdtempSync(join(tmpdir(), "hindsight-vendor-host-"));
    dirs.push(dir);
    const { default: registerPlugin } = await import("./index.js");
    const api = {
      config: {
        plugins: {
          entries: {
            "hindsight-openclaw": {
              config: { logLevel: "off", retainQueuePath: join(dir, "queue.jsonl"), ...config },
            },
          },
        },
      },
      registerService(registered: ServiceConfig) {
        service = registered;
      },
      on() {},
      logger: { info() {}, warn() {}, error() {} },
    } as unknown as MoltbotPluginAPI;
    registerPlugin(api);
    await service!.start().catch(() => {});
    return fetchSpy;
  };

  it("reaches no server and starts no daemon, even with an LLM provider configured", async () => {
    const fetchSpy = await start({ hindsightApiUrl: HOSTED, llmProvider: "ollama" });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(daemon.constructed).toBe(0);
  });

  it("does reach a server you run", async () => {
    const fetchSpy = await start({ hindsightApiUrl: "http://memory.test:8888" });
    const urls = fetchSpy.mock.calls.map(([url]: unknown[]) => String(url));
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((url: string) => url.startsWith("http://memory.test:8888"))).toBe(true);
  });

  it("is refused by the setup wizard, which writes nothing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "hindsight-vendor-host-"));
    dirs.push(dir);
    const args = parseCliArgs(["--mode", "api", "--api-url", HOSTED, "--no-token"]);
    await expect(runNonInteractive(args, join(dir, "openclaw.json"))).rejects.toThrow(/refuses/);
  });
});
