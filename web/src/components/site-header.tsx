"use client";

import { useState } from "react";
import { RotateCcw, FileStack, Plug } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConnectModelDialog } from "@/components/connect-model-dialog";
import { useAppStore } from "@/lib/store";
import { BAND_STYLES, PROVIDER_LABELS } from "@/lib/types";
import { cn } from "@/lib/utils";

export function SiteHeader() {
  const llm = useAppStore((state) => state.llm);
  const document = useAppStore((state) => state.document);
  const assessment = useAppStore((state) => state.assessment);
  const reset = useAppStore((state) => state.reset);
  const [dialogOpen, setDialogOpen] = useState(false);

  const band = assessment ? BAND_STYLES[assessment.assessment.band] : null;

  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-foreground text-background">
            <FileStack className="h-4 w-4" />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold">Forge</span>
            <span className="text-xs text-muted-foreground">
              PRD readiness dashboard
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {document && (
            <Badge variant="outline" className="hidden max-w-48 truncate sm:inline-flex">
              {document.filename}
            </Badge>
          )}
          {band && (
            <Badge className={cn("shrink-0 border text-sm", band.className)} variant="outline">
              {band.label}
            </Badge>
          )}

          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              llm
                ? "border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
                : "border-input bg-background text-muted-foreground hover:bg-muted",
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                llm ? "bg-emerald-500" : "bg-zinc-400",
              )}
            />
            {llm ? (
              <>
                {PROVIDER_LABELS[llm.provider]}
                {llm.model && (
                  <span className="hidden font-normal text-emerald-700 sm:inline dark:text-emerald-400">
                    · {llm.model}
                  </span>
                )}
              </>
            ) : (
              <>
                <Plug className="h-3 w-3" />
                Connect model
              </>
            )}
          </button>

          {(document || assessment) && (
            <Button variant="outline" size="sm" onClick={reset}>
              <RotateCcw className="h-3.5 w-3.5" />
              New assessment
            </Button>
          )}
        </div>
      </div>
      <ConnectModelDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </header>
  );
}
