import { useEffect, useState } from "react"
import { Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ResumeSessionButtonProps {
  sessionId: string
  directory: string
  name: string
}

const COPIED_MS = 2000

/** Copies `cd <directory> && claude --resume <sessionId>` to the clipboard. */
export function ResumeSessionButton({ sessionId, directory, name }: ResumeSessionButtonProps) {
  const command = `cd ${directory} && claude --resume ${sessionId}`
  const [copiedAt, setCopiedAt] = useState<number | null>(null)

  useEffect(() => {
    if (copiedAt === null) return
    const timer = setTimeout(() => setCopiedAt(null), COPIED_MS)
    return () => clearTimeout(timer)
  }, [copiedAt])

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={`Resume session ${name}`}
        title={command}
        onClick={() => {
          navigator.clipboard
            .writeText(command)
            .then(() => setCopiedAt(Date.now()))
            .catch(() => {})
        }}
      >
        <Terminal aria-hidden="true" />
      </Button>
      <span role="status" className="sr-only">
        {copiedAt !== null ? "Copied" : ""}
      </span>
    </>
  )
}
