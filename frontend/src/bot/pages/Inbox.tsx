import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useStore } from "../store";
import ConversationList from "../components/ConversationList";
import ChatPanel from "../components/ChatPanel";
import PropertiesPanel from "../components/PropertiesPanel";
import { isMobile } from "../lib/ui";


export default function Inbox() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { conversations, loading } = useStore();
  const { pathname, search } = useLocation();

  // The properties panel is a history entry, not component state: system back
  // closes it before leaving the chat, and it cannot survive a switch to another
  // conversation (that navigation drops the parameter).
  const drawer = new URLSearchParams(search).get("properties") === "1";
  const openProperties = () => (drawer ? navigate(-1) : navigate(`${pathname}?properties=1`));
  const closeProperties = () => navigate(-1);

  // Selection is URL-driven (/inbox/:id). No id: desktop opens the first
  // conversation, mobile shows the list first.
  const first = [...conversations].sort((a, b) => ((b.last_message_at ?? "") < (a.last_message_at ?? "") ? -1 : 1)).find((c) => c.status === "open") ?? conversations[0];
  const sel = id ?? (isMobile() || loading ? null : first?.id ?? null);
  const conv = sel ? conversations.find((c) => c.id === sel) : undefined;

  return (
    <div className="relative grid h-full overflow-hidden md:grid-cols-[320px_1fr]">
      <div className={`${sel ? "hidden" : "flex"} min-h-0 min-w-0 flex-col border-r border-line md:flex`}>
        <ConversationList selectedId={sel} onSelect={(cid) => navigate(`/bot/inbox/${cid}`)} />
      </div>

      <div className={`${sel ? "flex" : "hidden"} relative min-h-0 min-w-0 flex-col md:flex`}>
        {conv ? (
          <div className="relative min-h-0 flex-1">
            <ChatPanel conversation={conv} onBack={() => navigate("/bot/inbox")} onOpenProperties={openProperties} propertiesOpen={drawer} />
            <div onClick={closeProperties} className={`absolute inset-0 z-20 bg-black/20 transition-opacity ${drawer ? "opacity-100" : "pointer-events-none opacity-0"}`} />
            <div className={`absolute inset-y-0 right-0 z-30 w-full border-l border-line shadow-2xl transition-transform duration-200 sm:w-[360px] ${drawer ? "translate-x-0" : "translate-x-full"}`}>
              <PropertiesPanel conversationId={conv.id} onClose={closeProperties} />
            </div>
          </div>
        ) : (
          <div className="hidden h-full place-items-center text-[13px] text-muted md:grid">Select a conversation</div>
        )}
      </div>
    </div>
  );
}
