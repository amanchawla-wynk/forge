"use client";

import { useRef, useState } from "react";
import { FileText, UploadCloud, X } from "lucide-react";

import { cn } from "@/lib/utils";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".md", ".txt"];

interface DocumentUploadProps {
  file: File | null;
  onChange: (file: File | null) => void;
}

export function DocumentUpload({ file, onChange }: DocumentUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  function acceptFile(candidate: File | undefined) {
    if (!candidate) return;
    const extension = "." + candidate.name.split(".").pop()?.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) return;
    onChange(candidate);
  }

  return (
    <div className="space-y-1.5">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="hidden"
        onChange={(event) => acceptFile(event.target.files?.[0])}
      />
      {file ? (
        <div className="flex items-center justify-between rounded-lg border bg-muted/40 px-4 py-3">
          <div className="flex items-center gap-2 overflow-hidden">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate text-sm font-medium">{file.name}</span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB
            </span>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => event.key === "Enter" && inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            acceptFile(event.dataTransfer.files?.[0]);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center transition-colors",
            isDragging
              ? "border-foreground bg-muted/60"
              : "border-muted-foreground/30 hover:border-muted-foreground/60",
          )}
        >
          <UploadCloud className="h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium">
            Drop a PRD here, or click to browse
          </p>
          <p className="text-xs text-muted-foreground">
            PDF, DOCX, Markdown, or plain text
          </p>
        </div>
      )}
    </div>
  );
}
