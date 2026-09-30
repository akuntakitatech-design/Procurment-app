import { useEffect } from "react";
import api, { API } from "@/lib/api";

/**
 * Applies platform branding to the document <head> on every page:
 * - sets document.title to the platform name
 * - injects/updates the favicon <link> from the active platform favicon
 * Falls back to the static default favicon (public/favicon.ico) when none is set.
 */
export default function BrandingHead() {
  useEffect(() => {
    let cancelled = false;
    api.get("/platform-branding")
      .then((r) => {
        if (cancelled) return;
        const d = r.data || {};
        if (d.name) document.title = d.name;

        if (d.favicon_available) {
          const href = `${API}/platform-branding/favicon?v=${encodeURIComponent(d.favicon_version || "1")}`;
          const rels = ["icon", "shortcut icon", "apple-touch-icon"];
          rels.forEach((rel) => {
            let link = document.querySelector(`link[rel='${rel}']`);
            if (!link) {
              link = document.createElement("link");
              link.rel = rel;
              document.head.appendChild(link);
            }
            link.href = href;
          });
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return null;
}
