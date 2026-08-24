import { ChevronLeft, ChevronRight } from "lucide-react";
import { DayPicker } from "react-day-picker";
import { cn } from "../../lib/utils";

export function Calendar({ className, showOutsideDays = true, ...props }) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("kora-calendar", className)}
      components={{
        Chevron: ({ orientation, className: iconClassName }) => orientation === "left"
          ? <ChevronLeft className={cn("size-4", iconClassName)} />
          : <ChevronRight className={cn("size-4", iconClassName)} />
      }}
      {...props}
    />
  );
}
