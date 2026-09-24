import {
  AlertTriangle, CheckCircle2, FileQuestion, FilterX, LockKeyhole,
  SearchX, Settings2, Tags, WifiOff
} from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";

const typeIcons = {
  "first-use": FileQuestion,
  "no-results": SearchX,
  "no-labels": Tags,
  "insufficient-data": FilterX,
  "system-unavailable": WifiOff,
  "permission-limited": LockKeyhole,
  "configuration-required": Settings2,
  completed: CheckCircle2,
  error: AlertTriangle
};

export function OperationalEmptyState({
  type = "first-use",
  title,
  description,
  actionLabel,
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
  compact = false,
  className
}) {
  const Icon = typeIcons[type] || FileQuestion;
  return (
    <section className={cn("operational-empty-state", compact && "operational-empty-compact", className)} aria-label={title}>
      <Icon aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
        {(actionLabel || secondaryActionLabel) && <div className="operational-empty-actions">
          {actionLabel && <Button onClick={onAction}>{actionLabel}</Button>}
          {secondaryActionLabel && <Button variant="ghost" onClick={onSecondaryAction}>{secondaryActionLabel}</Button>}
        </div>}
      </div>
    </section>
  );
}
