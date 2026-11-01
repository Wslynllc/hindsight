import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The owner-visible promise of this build: with no usable server, every hook is inert and nothing
 * leaves the machine. Each case runs the real hooks over a real config file with the real client,
 * and watches the one exit every request goes through. The opted-in control proves the same hooks do
 * reach the network, so a pass cannot come from a hook that never got that far.
 */
let stdin = "";
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return {
    ...actual,
    readFileSync: (target: unknown, ...rest: unknown[]) =>
      target === 0 ? stdin : (actual.readFileSync as (...a: unknown[]) => unknown)(target, ...rest),
  };
});

const SERVER = "http://memory.test:8888";

describe("a config that names no usable server", () => {
  let root: string;
  let configFile: string;
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "hs-fail-closed-"));
    execFileSync("git", ["init", "-q", root]);
    configFile = join(root, "coding-agent.json");
    vi.stubEnv("HINDSIGHT_CONFIG", configFile);
    vi.stubEnv("HINDSIGHT_DIAG_FILE", join(root, "diag.log"));
    vi.stubEnv("HINDSIGHT_API_URL", "");
    vi.stubEnv("HINDSIGHT_OPT_IN_ONLY", "");
    const transcript = join(root, "session.jsonl");
    writeFileSync(
      transcript,
      JSON.stringify({
        type: "user",
        timestamp: "2026-01-01T00:00:00Z",
        message: { role: "user", content: "we use zod for validation" },
      })
    );
    stdin = JSON.stringify({
      cwd: root,
      session_id: `sess-${root.split("/").pop()}`,
      prompt: "what do we use for validation?",
      transcript_path: transcript,
    });
    fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    vi.spyOn(process.stdout, "write").mockReturnValue(true);
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    rmSync(root, { recursive: true, force: true });
  });

  /** Fires session start, prompt and stop for a host, on a module graph that reads this test's env. */
  const runEveryHook = async () => {
    vi.resetModules();
    const { HOOK_HARNESSES } = await import("../harness/hook-lifecycle");
    const { runSessionStartHook } = await import("./session-start");
    const { runHook } = await import("./hook");
    const { runRetainHook } = await import("./retain-hook");
    const host = HOOK_HARNESSES["claude-code"];
    await runSessionStartHook(host.sessionStart);
    await runHook(host.prompt);
    await runRetainHook(host.retain);
  };

  it.each([
    ["no config file and no env", undefined, {}],
    ["an unparseable file, whatever the env says", "{not json", envServer()],
    ["a file that is not an object", "[]", envServer()],
    ["a null file", "null", envServer()],
    ["a file still in cloud mode", JSON.stringify(live({ serverMode: "cloud" })), {}],
    ["a file still in daemon mode", JSON.stringify(live({ serverMode: "daemon" })), {}],
    [
      "the vendor's hosted API",
      JSON.stringify(live({ apiUrl: "https://api.hindsight.vectorize.io" })),
      {},
    ],
    ["any other vendor host", JSON.stringify(live({ apiUrl: "HTTPS://Vectorize.IO./v1" })), {}],
    [
      "the vendor's host from the environment",
      undefined,
      { HINDSIGHT_API_URL: "https://api.hindsight.vectorize.io", HINDSIGHT_OPT_IN_ONLY: "false" },
    ],
    ["a URL that is not one", JSON.stringify(live({ apiUrl: "memory.test:8888" })), {}],
    ["a URL that is not a string", JSON.stringify(live({ apiUrl: 8888 })), {}],
    ["an empty URL", JSON.stringify(live({ apiUrl: "" })), {}],
    ["no URL with opt-in switched off", JSON.stringify({ optInOnly: false }), {}],
  ])("sends nothing for %s", async (_name, file, env) => {
    if (file !== undefined) writeFileSync(configFile, file);
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
    await runEveryHook();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends nothing for a project outside optInPaths, with a server configured", async () => {
    writeFileSync(configFile, JSON.stringify({ apiUrl: SERVER, optInPaths: [join(root, "other")] }));
    await runEveryHook();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends nothing when only the environment names a server and no project is opted in", async () => {
    vi.stubEnv("HINDSIGHT_API_URL", SERVER);
    await runEveryHook();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does talk to the configured server once the project is opted in", async () => {
    writeFileSync(configFile, JSON.stringify({ ...live(), optInOnly: true, optInPaths: [root] }));
    await runEveryHook();
    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((url) => url.startsWith(SERVER))).toBe(true);
  });

  /** A config that would be live, apart from whatever the case overrides. Opt-in is off so that the
   *  only thing standing between these cases and the network is the server check. */
  function live(overrides: Record<string, unknown> = {}) {
    return { apiUrl: SERVER, autoSeed: false, optInOnly: false, ...overrides };
  }
  function envServer() {
    return { HINDSIGHT_API_URL: SERVER, HINDSIGHT_OPT_IN_ONLY: "false" };
  }
});
