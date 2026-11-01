/**
 * Styled terminal renderer for the installer CLI (clack/Vercel-style rail).
 *
 * The install/uninstall engine reports plain prefixed strings ("<harness>: <what happened>")
 * through InstallCtx.log — a deliberately dumb channel that tests and programmatic callers
 * consume as-is. This module is the only place that turns that stream into the framed,
 * colorized output the interactive CLI shows: a message prefixed with a known harness name
 * opens a step group, the phrasing adapters already use picks the ✓/▲/✖ symbol, and absolute
 * paths under $HOME are shortened to ~. The renderer sits ON the log channel rather than
 * threading a structured UI through every adapter, so the engine stays renderer-agnostic and
 * the installer tests keep asserting on plain text.
 *
 * Zero-dependency by design: the installer must run from a bare `npm install -g` with nothing
 * but node builtins, so no chalk/@clack/prompts.
 */
import { brandWord } from "./core/brand";

export interface InstallerUiOptions {
  home: string;
  /** argv[2], used by the outro to say what completed (install vs uninstall vs usage). */
  command?: string;
  version?: string;
  /** Names whose "<name>: " prefix opens a step group AND count as installed agents. */
  harnessNames: string[];
  /** Extra group names (e.g. "server") that render like a harness but aren't agents. */
  auxNames?: string[];
  /** Where settings actually live (HINDSIGHT_CONFIG override); the outro names this file. */
  configPath?: string;
  /** Test overrides: deterministic colors, captured output, fixed clock. */
  colors?: boolean;
  write?: (line: string) => void;
  now?: () => number;
}

export interface InstallerUi {
  intro(): void;
  /** Style an interactive question so readline prompts sit on the rail like log lines. */
  prompt(question: string): string;
  log(message: string): void;
  outro(exitCode: number): void;
}

/**
 * Adapter messages are prose, not levels — severity is inferred from the phrasing they already
 * use. Every "warn" phrasing means "wired, but something was skipped or needs a manual step";
 * "error" phrasings only occur on run()'s guard paths, which abort before touching any config.
 */
const WARN_RE =
  /\bskipped\b|could not|manually|preserved|did not finish|unrecognised|add `hooks = true`/i;
const ERROR_RE = /unknown harness|no supported coding agents|name a harness/;
const INFO_RE = /^usage:|^detected: |\?$/; // a line ending in "?" introduces a question, not a result

/** run() also marks severity itself with a leading emoji; adopt it instead of double-marking. */
const EMOJI_KIND: Record<string, "ok" | "warn" | "error"> = {
  "✅": "ok",
  "⚠️": "warn",
  "❌": "error",
};

export function createInstallerUi(o: InstallerUiOptions): InstallerUi {
  const sink = o.write ?? ((line: string) => console.log(line));
  // Track the last emitted line so spacer rails never double up (intro/outro/group all want a
  // blank `│` next to them, and any two of those can be adjacent).
  let lastLine = "";
  const write = (line: string): void => {
    lastLine = line;
    sink(line);
  };
  // Honor NO_COLOR (https://no-color.org) and drop ANSI when output is piped; the frame itself
  // stays, so captured logs keep the structure.
  const colors =
    o.colors ??
    (process.stdout.isTTY === true &&
      process.env.NO_COLOR === undefined &&
      process.env.TERM !== "dumb");
  const now = o.now ?? Date.now;
  const paint = (code: string, s: string): string => (colors ? `\x1b[${code}m${s}\x1b[0m` : s);
  const dim = (s: string): string => paint("2", s);
  const bold = (s: string): string => paint("1", s);
  const green = (s: string): string => paint("32", s);
  const yellow = (s: string): string => paint("33", s);
  const red = (s: string): string => paint("31", s);
  const cyan = (s: string): string => paint("36", s);
  const bar = dim("│");
  const symbol = { ok: green("✓"), warn: yellow("▲"), error: red("✖"), info: dim("○") };

  // Messages embed absolute config paths; shorten $HOME so the action stays the eye-catcher.
  const tidy = (s: string): string => s.replaceAll(o.home, "~");
  // The lookbehind keeps URL slashes ("http://…") from being treated as a path start.
  const dimPaths = (s: string): string => s.replace(/(?<![:\w/])~?\/[^\s"',)]+/g, (m) => dim(m));

  const prefixRe = new RegExp(`^(${[...o.harnessNames, ...(o.auxNames ?? [])].join("|")}): `);
  const startedAt = now();
  let group: string | null = null;
  // Only harness groups count toward the outro's "Installed N agents" — the server-setup group
  // is a step, not an agent.
  let groups = 0;

  function classify(line: string): keyof typeof symbol {
    if (INFO_RE.test(line)) return "info";
    if (ERROR_RE.test(line)) return "error";
    if (WARN_RE.test(line)) return "warn";
    return "ok";
  }

  const spacer = (): void => {
    if (lastLine !== bar) write(bar);
  };

  function openGroup(name: string): void {
    spacer();
    write(`${cyan("◇")}  ${bold(name)}`);
    group = name;
    if (o.harnessNames.includes(name)) groups++;
  }

  return {
    intro(): void {
      write("");
      write(
        `${dim("┌")}  ${colors ? brandWord() : "Hindsight"} ${bold("coding agents")}` +
          (o.version ? `  ${dim(`v${o.version}`)}` : "")
      );
      write(bar);
    },

    /** Style an interactive question so readline prompts sit on the rail like log lines. */
    prompt(question: string): string {
      return `${bar}  ${question}`;
    },

    log(message: string): void {
      const text = tidy(message).replace(/^\n+|\n+$/g, "");
      if (!text) return;
      const lines = text.split("\n");
      // A message that begins indented is detail for the previous one (e.g. the re-run command a
      // failed history import prints as its own log call) — keep it quiet, not behind a fresh ✓.
      if (/^\s/.test(lines[0])) {
        for (const l of lines) write(`${bar}    ${dim(l.trim())}`);
        return;
      }
      // Emoji severity comes first: preflight failures read "❌ devin-cli: …", and the harness
      // prefix must still open its group once the marker is stripped.
      const emoji = lines[0].match(/^(✅|❌|⚠️)\s*/u);
      if (emoji) lines[0] = lines[0].slice(emoji[0].length);
      const prefixed = lines[0].match(prefixRe);
      if (prefixed) {
        if (prefixed[1] !== group) openGroup(prefixed[1]);
        lines[0] = lines[0].slice(prefixed[0].length);
      }
      const kind = emoji ? EMOJI_KIND[emoji[1]] : classify(lines[0]);
      write(`${bar}  ${symbol[kind]} ${kind === "info" ? dim(lines[0]) : dimPaths(lines[0])}`);
      // Continuation lines carry detail (a command to run, the harness list) — keep them quiet.
      for (const rest of lines.slice(1)) write(`${bar}    ${dim(rest.trim())}`);
    },

    outro(exitCode: number): void {
      spacer();
      if (exitCode !== 0) {
        // Guard paths exit before anything was wired; a preflight-blocked harness exits non-zero
        // AFTER wiring the others (run() only opens groups for work it actually did).
        write(
          `${dim("└")}  ${red("✖")} ${groups ? "Completed with errors — see above." : "Aborted — nothing was changed."}`
        );
      } else if (o.command === "install" || o.command === "uninstall") {
        const secs = ((now() - startedAt) / 1000).toFixed(1);
        const agents = `${groups} agent${groups === 1 ? "" : "s"}`;
        if (o.command === "install") {
          const settings = o.configPath ? tidy(o.configPath) : "~/.hindsight/coding-agent.json";
          write(`${dim("└")}  ${green("✓")} Installed ${agents} in ${secs}s`);
          write(`   ${dim(`Start a session — settings live in ${settings}.`)}`);
        } else {
          write(
            `${dim("└")}  ${green("✓")} Uninstalled ${agents} in ${secs}s — Hindsight entries removed, *.hindsight-backup files left in place.`
          );
        }
      } else if (o.command === "update") {
        write(
          `${dim("└")}  ${green("✓")} Runtime up to date${o.version ? ` (v${o.version})` : ""}`
        );
      } else {
        // Bare usage: nothing happened, just close the frame.
        write(dim("└"));
      }
      write("");
    },
  };
}
