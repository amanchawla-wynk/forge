"use client";

import { useState } from "react";
import { Loader2, PlugZap } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LLMSetupForm } from "@/components/setup/llm-setup-form";
import { ApiError, verifyLLM } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { LLMConfig } from "@/lib/types";

interface ConnectModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ConnectModelDialog({ open, onOpenChange }: ConnectModelDialogProps) {
  const storedLLM = useAppStore((state) => state.llm);
  const setLLM = useAppStore((state) => state.setLLM);

  const [draft, setDraft] = useState<LLMConfig>(
    storedLLM ?? { provider: "anthropic", model: "claude-opus-5-5", api_key: "" },
  );
  const [isVerifying, setIsVerifying] = useState(false);

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setDraft(storedLLM ?? { provider: "anthropic", model: "claude-opus-5-5", api_key: "" });
    }
    onOpenChange(nextOpen);
  }

  async function handleConnect() {
    if (!draft.api_key.trim()) return;
    setIsVerifying(true);
    try {
      const result = await verifyLLM(draft);
      setLLM(draft);
      toast.success("Connected", {
        description: `Verified with model ${result.model}.`,
      });
      onOpenChange(false);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Could not reach the local Forge dashboard backend. Is it running on port 8000?";
      toast.error("Could not connect", { description: message });
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Connect a model</DialogTitle>
          <DialogDescription>
            Bring your own key. It stays in this browser tab for the session
            only and is forwarded to your local Forge backend per request
            &mdash; never stored on disk or logged.
          </DialogDescription>
        </DialogHeader>

        <LLMSetupForm value={draft} onChange={setDraft} />

        <DialogFooter>
          <Button
            className="w-full sm:w-auto"
            disabled={!draft.api_key.trim() || isVerifying}
            onClick={handleConnect}
          >
            {isVerifying ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Testing connection&hellip;
              </>
            ) : (
              <>
                <PlugZap className="h-4 w-4" />
                Test &amp; connect
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
