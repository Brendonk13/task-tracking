import { Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ResumeSessionButtonProps {
  sessionId: string
  directory: string
  name: string
}

/** Copies `cd <directory> && claude --resume <sessionId>` to the clipboard. */
export function ResumeSessionButton({ sessionId, directory, name }: ResumeSessionButtonProps) {
  const command = `cd ${directory} && claude --resume ${sessionId}`
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={`Resume session ${name}`}
      title={command}
      onClick={() => void navigator.clipboard.writeText(command)}
    >
      <Terminal aria-hidden="true" />
    </Button>
  )
}
