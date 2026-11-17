import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { EMPTY_STATE } from "../styles/recipes.ts";

interface Props {
  icon: LucideIcon;
  text: string;
  action?: ReactNode;
}

// A quiet icon, one line and one action, for a list with nothing in it
export function EmptyState({ icon: Icon, text, action }: Props) {
  return (
    <div className={EMPTY_STATE}>
      <Icon size={48} strokeWidth={1.75} aria-hidden="true" />
      <p>{text}</p>
      {action}
    </div>
  );
}
