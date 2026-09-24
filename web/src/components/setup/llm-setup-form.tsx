"use client";

import { useState } from "react";
import { Eye, EyeOff, KeyRound } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  PROVIDER_DEFAULT_MODELS,
  PROVIDER_LABELS,
  PROVIDER_MODEL_OPTIONAL,
  type LLMConfig,
  type Provider,
} from "@/lib/types";

interface LLMSetupFormProps {
  value: LLMConfig;
  onChange: (value: LLMConfig) => void;
}

export function LLMSetupForm({ value, onChange }: LLMSetupFormProps) {
  const [showKey, setShowKey] = useState(false);
  const isCursor = value.provider === "cursor";
  const defaultModels = PROVIDER_DEFAULT_MODELS[value.provider];

  function handleProviderChange(provider: Provider) {
    onChange({
      ...value,
      provider,
      model: PROVIDER_DEFAULT_MODELS[provider][0] ?? "",
    });
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="provider">Model provider</Label>
        <Select value={value.provider} onValueChange={handleProviderChange}>
          <SelectTrigger id="provider" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(PROVIDER_LABELS) as Provider[]).map((provider) => (
              <SelectItem key={provider} value={provider}>
                {PROVIDER_LABELS[provider]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isCursor && (
          <p className="text-xs text-muted-foreground">
            Runs extraction through a short-lived Cursor Cloud Agent instead
            of calling a provider directly. Slower, billed against your
            Cursor plan/agent quota, and your document text is sent to
            Cursor&apos;s cloud infrastructure for that run.
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="model">
          Model{" "}
          {PROVIDER_MODEL_OPTIONAL[value.provider] && (
            <span className="text-muted-foreground">(optional)</span>
          )}
        </Label>
        {defaultModels.length > 0 && (
          <Select
            value={
              defaultModels.includes(value.model) ? value.model : "__custom__"
            }
            onValueChange={(selected) =>
              selected !== "__custom__" &&
              onChange({ ...value, model: selected })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {defaultModels.map((model) => (
                <SelectItem key={model} value={model}>
                  {model}
                </SelectItem>
              ))}
              <SelectItem value="__custom__">Custom model id&hellip;</SelectItem>
            </SelectContent>
          </Select>
        )}
        <Input
          id="model"
          value={value.model}
          onChange={(event) => onChange({ ...value, model: event.target.value })}
          placeholder={
            isCursor
              ? "leave blank to use your Cursor default model"
              : "exact model id, e.g. claude-opus-5-5"
          }
          className={defaultModels.length > 0 ? "mt-1.5" : undefined}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="api-key">
          {isCursor ? "Cursor API key" : "API key"}
        </Label>
        <div className="relative">
          <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="api-key"
            type={showKey ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={value.api_key}
            onChange={(event) =>
              onChange({ ...value, api_key: event.target.value })
            }
            placeholder={
              isCursor ? "cursor.com/dashboard/api key" : `${PROVIDER_LABELS[value.provider]} API key`
            }
            className="pl-9 pr-9"
          />
          <button
            type="button"
            onClick={() => setShowKey((show) => !show)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showKey ? "Hide API key" : "Show API key"}
          >
            {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
          {isCursor ? (
            <>
              Generate this at{" "}
              <span className="font-medium text-foreground">
                cursor.com/dashboard/api
              </span>{" "}
              &mdash; it is a Cursor account key, not an Anthropic/OpenAI/
              Gemini key. Stays in this browser tab for the session only,
              sent to your local Forge backend per request, never stored on
              disk or logged.
            </>
          ) : (
            <>
              Stays in this browser tab for the session only. Sent to your
              local Forge backend per request and forwarded straight to{" "}
              {PROVIDER_LABELS[value.provider]} &mdash; never stored on disk
              or logged.
            </>
          )}
        </p>
      </div>
    </div>
  );
}
