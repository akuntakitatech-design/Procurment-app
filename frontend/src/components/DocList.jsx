import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { Button } from "@/components/ui/button";
import { TxnList } from "@/components/TxnList";
import { Plus } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { printDoc } from "@/lib/print";

export function DocList({ title, subtitle, txType, createPath, columns, rows, basePath, testidPrefix, module, printType, printOpts, onReload, ...rest }) {
  const nav = useNavigate();
  const { can } = useAuth();
  const print = printType ? async (r) => { const d = await api.get(`${basePath}/${r.id}`); printDoc(printType, d.data, printOpts || {}); } : undefined;
  return (
    <div>
      {(() => {
        const createBtn = createPath && can("create") && <Button onClick={() => nav(createPath)} data-testid={`${testidPrefix}-create-btn`}><Plus className="h-4 w-4 mr-2" />Buat Baru</Button>;
        return txType
          ? <TransactionPageHeader type={txType} mode="list">{createBtn}</TransactionPageHeader>
          : <PageHeader title={title} subtitle={subtitle}>{createBtn}</PageHeader>;
      })()}
      <TxnList module={module} columns={columns} rows={rows} testidPrefix={testidPrefix} onReload={onReload}
        onOpen={(r) => basePath && nav(`${basePath}/${r.id}`)} onPrint={print} onEdit={(r) => nav(`${basePath}/${r.id}?edit=1`)} {...rest} />
    </div>
  );
}
