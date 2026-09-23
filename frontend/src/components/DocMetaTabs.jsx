import { AttachmentPanel, AuditPanel } from "@/components/DocMeta";
import { LifecycleTracker } from "@/components/LifecycleTracker";
import { ChevronDown, Link2, Paperclip, History } from "lucide-react";

const LIFECYCLE_ENTITIES = new Set(["mro", "ro", "po", "do", "mi"]);

function InlineSection({ icon: Icon, title, children, open = false }) {
  return (
    <details className="group rounded-xl border bg-card shadow-sm" open={open}>
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 select-none">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Icon className="h-4 w-4" /></div>
        <span className="flex-1 font-head text-sm font-semibold">{title}</span>
        <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t p-4">{children}</div>
    </details>
  );
}

/**
 * Historical name kept for compatibility. Transaction detail, references,
 * attachments, and audit stay on the same page so users do not lose context.
 */
export function DocMetaTabs({ entity, entityId, references, children }) {
  const showLifecycle = !!entityId && LIFECYCLE_ENTITIES.has(entity);
  return (
    <div className="space-y-4 mt-2">
      {showLifecycle && <LifecycleTracker entity={entity} docId={entityId} />}

      {children}

      {references && (
        <InlineSection icon={Link2} title="Referensi & Alur Dokumen" open>
          {references}
        </InlineSection>
      )}

      <InlineSection icon={Paperclip} title="Lampiran" open>
        <AttachmentPanel entity={entity} entityId={entityId} />
      </InlineSection>

      <InlineSection icon={History} title="Riwayat Aktivitas">
        <AuditPanel entity={entity} entityId={entityId} />
      </InlineSection>
    </div>
  );
}
