import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Plus, Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export function DocList({ title, subtitle, createPath, columns, rows, basePath, testidPrefix }) {
  const nav = useNavigate();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const filtered = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <PageHeader title={title} subtitle={subtitle}>
        {createPath && can("create") && (
          <Button onClick={() => nav(createPath)} data-testid={`${testidPrefix}-create-btn`}>
            <Plus className="h-4 w-4 mr-2" />Buat Baru
          </Button>
        )}
      </PageHeader>
      <div className="relative max-w-sm mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input placeholder="Cari..." value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" data-testid={`${testidPrefix}-search`} />
      </div>
      <div className="border rounded-md overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-sm zebra">
          <thead className="bg-muted">
            <tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {columns.map((c) => <th key={c.key} className={`p-3 ${c.num ? "text-right" : ""}`}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && <tr><td colSpan={columns.length} className="p-8 text-center text-muted-foreground">Belum ada data</td></tr>}
            {filtered.map((r) => (
              <tr key={r.id} onClick={() => basePath && nav(`${basePath}/${r.id}`)} data-testid={`${testidPrefix}-row-${r.no || r.id}`}
                className="border-t hover:bg-accent/40 cursor-pointer transition-colors">
                {columns.map((c) => (
                  <td key={c.key} className={`p-3 ${c.mono ? "font-mono text-xs font-semibold" : ""} ${c.num ? "text-right tabular-nums" : ""}`}>
                    {c.render ? c.render(r) : c.status ? <StatusBadge status={r[c.key]} /> : (r[c.key] ?? "-")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
