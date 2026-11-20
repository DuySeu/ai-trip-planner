// The site name of a source url, without "www."; the url itself when it cannot be read
export function siteOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
