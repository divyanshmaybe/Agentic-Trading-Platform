import { useEffect, useRef, useState, useCallback } from "react";
import type { LowRiskEventDTO } from "@/lib/types/lowrisk";

type ConnectionStatus = "connecting" | "open" | "closed" | "error";

/**
 * LowRiskEvent - Internal type for UI components with Date objects
 * Converted from LowRiskEventDTO in hook for easier date handling
 */
export interface LowRiskEvent {
  id: string;
  userId: string;
  kind: "info" | "industry" | "stock" | "report" | "reasoning" | "summary" | "stage";
  eventType: string | null;
  status: string | null;
  content: any | null;
  rawPayload: any;
  createdAt: Date;
  eventTime: Date | null;
}

/**
 * Convert LowRiskEventDTO to LowRiskEvent (ISO strings -> Date objects)
 */
function dtoToLowRiskEvent(dto: LowRiskEventDTO): LowRiskEvent {
  return {
    ...dto,
    createdAt: new Date(dto.createdAt),
    eventTime: dto.eventTime ? new Date(dto.eventTime) : null,
  };
}

interface UseLowRiskEventsReturn {
  events: LowRiskEvent[];
  loading: boolean;
  status: ConnectionStatus;
  startStreaming: () => void;
  stopStreaming: () => void;
  streaming: boolean;
  hasSummary: boolean;
  clearEvents: () => void;
}

export function useLowRiskEvents(): UseLowRiskEventsReturn {
  const [events, setEvents] = useState<LowRiskEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<ConnectionStatus>("closed");
  const [streaming, setStreaming] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const autoStartAttemptedRef = useRef<boolean>(false);

  // Helper function to merge events and deduplicate by ID
  const mergeEvents = useCallback((existing: LowRiskEvent[], incoming: LowRiskEvent[]): LowRiskEvent[] => {
    const map = new Map<string, LowRiskEvent>();
    
    // Add all existing events to map
    existing.forEach(e => map.set(e.id, e));
    
    // Add or update with incoming events (incoming takes precedence for same ID)
    incoming.forEach(e => map.set(e.id, e));
    
    // Convert map values to array and sort by createdAt descending
    return Array.from(map.values()).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
  }, []);

  // Fetch initial events
  useEffect(() => {
    let cancelled = false;

    async function fetchInitial() {
      try {
        const response = await fetch("/api/notifications/lowrisk", {
          credentials: "include",
        });

        if (!response.ok) {
          throw new Error(`Failed to fetch low-risk events: ${response.statusText}`);
        }

        const data = await response.json();
        
        // Handle both direct array and wrapped response formats
        const eventsData: LowRiskEventDTO[] = Array.isArray(data) ? data : (data.events || []);

        if (!cancelled) {
          // Convert LowRiskEventDTO (ISO strings) to LowRiskEvent (Date objects)
          const lowRiskEvents = eventsData.map(dtoToLowRiskEvent);

          // Sort by createdAt descending (newest first)
          lowRiskEvents.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

          // Merge with existing events (in case SSE already added some)
          setEvents((prev) => {
            const merged = mergeEvents(prev, lowRiskEvents);
            return merged;
          });
          
          setLoading(false);
        }
      } catch (error) {
        console.error("[LowRisk Events] Failed to fetch initial:", error);
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchInitial();

    return () => {
      cancelled = true;
    };
  }, [mergeEvents]);

  // Manual SSE connection start function
  const startStreaming = useCallback(() => {
    // Don't start if already streaming
    if (eventSourceRef.current) {
      return;
    }

    setStatus("connecting");
    setStreaming(true);

    // Find the most recent event to resume from where we left off
    const lastEvent = events.length > 0 
      ? events.reduce((latest, current) => 
          current.createdAt > latest.createdAt ? current : latest
        )
      : null;

    // Build URL with lastEventId and lastEventCreatedAt if we have events
    let streamUrl = "/api/notifications/lowrisk/stream";
    if (lastEvent) {
      const params = new URLSearchParams({
        lastEventId: lastEvent.id,
        lastEventCreatedAt: lastEvent.createdAt.toISOString(),
      });
      streamUrl = `${streamUrl}?${params.toString()}`;
    }

    const eventSource = new EventSource(streamUrl, {
      withCredentials: true,
    });
    eventSourceRef.current = eventSource;

    const handleOpen = () => {
      setStatus("open");
    };

    const handleLowRisk = (event: MessageEvent<string>) => {
      try {
        const dto: LowRiskEventDTO = JSON.parse(event.data);

        // Convert LowRiskEventDTO to LowRiskEvent (Date objects)
        const lowRiskEvent = dtoToLowRiskEvent(dto);

        // Merge with existing events (handles deduplication by ID)
        setEvents((prev) => mergeEvents(prev, [lowRiskEvent]));

        // Close stream after summary event
        if (lowRiskEvent.kind === "summary") {
          console.log("[LowRisk Events] Summary event received, closing stream");
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
            setStreaming(false);
            setStatus("closed");
          }
        }
      } catch (err) {
        console.warn("[LowRisk Events] Failed to parse low-risk event:", err);
      }
    };

    const handleError = (event: Event) => {
      setStatus("error");
      setStreaming(false);
      console.warn("[LowRisk Events] SSE error:", event);
      
      // Clean up on error
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };

    const handleStatus = () => {
      setStatus("open");
    };

    const handlePing = () => {
      // Keep-alive ping
    };

    eventSource.addEventListener("open", handleOpen);
    eventSource.addEventListener("status", handleStatus);
    eventSource.addEventListener("lowrisk", handleLowRisk);
    eventSource.addEventListener("error", handleError);
    eventSource.addEventListener("ping", handlePing);
  }, [mergeEvents]);

  // Manual SSE connection stop function
  const stopStreaming = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setStreaming(false);
      setStatus("closed");
    }
  }, []);

  // Clear all events function
  const clearEvents = useCallback(() => {
    setEvents([]);
    // Reset auto-start attempt flag so streaming can start fresh
    autoStartAttemptedRef.current = false;
  }, []);

  // Calculate if events contain a summary event
  const hasSummary = events.some((event) => event.kind === "summary");

  // Auto-start streaming if events exist but no summary
  useEffect(() => {
    // Only attempt auto-start once and when conditions are met
    if (
      !loading &&
      events.length > 0 &&
      !hasSummary &&
      !streaming &&
      !eventSourceRef.current &&
      !autoStartAttemptedRef.current
    ) {
      console.log("[LowRisk Events] Auto-starting stream (events exist but no summary)");
      autoStartAttemptedRef.current = true;
      startStreaming();
    }
  }, [loading, events.length, hasSummary, streaming, startStreaming]);


  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setStreaming(false);
      setStatus("closed");
    };
  }, []);

  return {
    events,
    loading,
    status,
    startStreaming,
    stopStreaming,
    streaming,
    hasSummary,
    clearEvents,
  };
}

