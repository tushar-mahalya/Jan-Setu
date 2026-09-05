import { useEffect, useState } from "react";

/**
 * Renders a complaint's evidence photo. The endpoints require an Authorization
 * header, which a plain <img src> cannot send, so the bytes are fetched into an
 * object URL and revoked on unmount. `load` is injected because the citizen and
 * official consoles authenticate differently.
 */
export function EvidencePhoto({
  path,
  alt,
  load,
  caption,
}: {
  path: string;
  alt: string;
  load: (path: string) => Promise<string>;
  caption?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let active = true;
    setSrc(null);
    setFailed(false);
    load(path)
      .then((url) => {
        objectUrl = url;
        if (active) setSrc(url);
        else URL.revokeObjectURL(url);
      })
      .catch(() => { if (active) setFailed(true); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, load]);

  if (failed) return <p className="evidence-photo__error">Photo could not be loaded.</p>;
  if (!src) return <div className="evidence-photo__pending" aria-busy="true" />;
  return <figure className="evidence-photo">
    <img src={src} alt={alt} />
    {caption && <figcaption>{caption}</figcaption>}
  </figure>;
}
