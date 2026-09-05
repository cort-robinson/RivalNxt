import { useState } from "react";
import { createBackup } from "../lib/api";
import { UpdatePanel } from "./UpdatePanel";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

export function AppUpdateDialog({ open, onOpenChange, onBackupCreated }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onBackupCreated?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value); }}>
    <DialogContent className="max-w-xl">
      <DialogHeader>
        <DialogTitle>Update RivalNxt</DialogTitle>
        <DialogDescription>Review a release and choose when to install it.</DialogDescription>
      </DialogHeader>
      <UpdatePanel onBusyChange={setBusy} beforeInstall={async () => {
        const backup = await createBackup("Before app update");
        if (!backup.ok) throw new Error("The safety backup did not complete.");
        onBackupCreated?.();
      }} />
    </DialogContent>
  </Dialog>;
}
