/**
 * This build talks only to servers the user runs, so the vendor's hosted domain is refused wherever
 * a Hindsight URL enters. Matches the host however it is written, with or without a scheme, and
 * nothing else: `notvectorize.io` and a path containing the name are not the vendor.
 */
export function isVendorHosted(url: unknown): boolean {
  if (typeof url !== "string") return false;
  const text = url.trim();
  try {
    const { hostname } = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `http://${text}`);
    return /(^|\.)vectorize\.io\.?$/i.test(hostname);
  } catch {
    return false;
  }
}

export const VENDOR_HOSTED_REFUSED =
  "hindsightApiUrl points at a vectorize.io host, which this build refuses. " +
  "Set it to a server you run.";
