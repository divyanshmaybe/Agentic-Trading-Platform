import { useEffect, useRef, useState, useCallback } from "react";
import type { NotificationDTO, Notification } from "@/lib/types/notifications";
import { dtoToNotification } from "@/lib/types/notifications";

type ConnectionStatus = "connecting" | "open" | "closed" | "error";

interface UseIntradayNotificationsReturn {
  notifications: Notification[];
  loading: boolean;
  dismiss: (id: string) => Promise<void>;
  dismissMany: (ids: string[]) => Promise<void>;
  dismissAll: () => Promise<void>;
}

export function useIntradayNotifications(): UseIntradayNotificationsReturn {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  const eventSourceRef = useRef<EventSource | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const dismissManyTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pendingDismissIdsRef = useRef<Set<string>>(new Set());

  // Helper function to merge notifications and deduplicate by ID
  const mergeNotifications = useCallback((existing: Notification[], incoming: Notification[]): Notification[] => {
    const map = new Map<string, Notification>();
    
    // Add all existing notifications to map
    existing.forEach(n => map.set(n.id, n));
    
    // Add or update with incoming notifications (incoming takes precedence for same ID)
    incoming.forEach(n => map.set(n.id, n));
    
    // Convert map values to array and sort by createdAt descending
    return Array.from(map.values()).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
  }, []);

  // Fetch initial notifications
  useEffect(() => {
    let cancelled = false;

    async function fetchInitial() {
      try {
        const response = await fetch("/api/notifications/intraday", {
          credentials: "include",
        });

        if (!response.ok) {
          throw new Error(`Failed to fetch notifications: ${response.statusText}`);
        }

        const data = await response.json();
        
        // Handle both direct array and wrapped response formats
        const notificationsData: NotificationDTO[] = Array.isArray(data) ? data : (data.notifications || []);

        if (!cancelled) {
          // Intraday shows ALL notifications (no filtering)
          // Convert NotificationDTO (ISO strings) to Notification (Date objects)
          const notifications = notificationsData.map(dtoToNotification);

          // Sort by createdAt descending (newest first)
          notifications.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

          // Merge with existing notifications (in case SSE already added some)
          setNotifications((prev) => mergeNotifications(prev, notifications));
          
          // Mark all fetched notifications as seen
          notificationsData.forEach((n) => seenIdsRef.current.add(n.id));
          setLoading(false);
        }
      } catch (error) {
        console.error("[Intraday Notifications] Failed to fetch initial:", error);
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchInitial();

    return () => {
      cancelled = true;
    };
  }, [mergeNotifications]);

  // SSE connection
  useEffect(() => {
    setStatus("connecting");

    const eventSource = new EventSource("/api/notifications/intraday/stream", {
      withCredentials: true,
    });
    eventSourceRef.current = eventSource;

    const handleOpen = () => {
      setStatus("open");
    };

    const handleNotification = (event: MessageEvent<string>) => {
      try {
        const dto: NotificationDTO = JSON.parse(event.data);

        // Intraday shows ALL notifications (no filtering)
        // Mark as seen (even if we merge, this prevents duplicate processing)
        seenIdsRef.current.add(dto.id);

        // Convert NotificationDTO to Notification (Date objects)
        const notification = dtoToNotification(dto);

        // Merge with existing notifications (handles deduplication by ID)
        setNotifications((prev) => mergeNotifications(prev, [notification]));
      } catch (err) {
        console.warn("[Intraday Notifications] Failed to parse notification:", err);
      }
    };

    const handleError = (event: Event) => {
      setStatus("error");
      console.warn("[Intraday Notifications] SSE error:", event);
    };

    const handleStatus = () => {
      setStatus("open");
    };

    const handlePing = () => {
      // Keep-alive ping
    };

    eventSource.addEventListener("open", handleOpen);
    eventSource.addEventListener("status", handleStatus);
    eventSource.addEventListener("notification", handleNotification);
    eventSource.addEventListener("error", handleError);
    eventSource.addEventListener("ping", handlePing);

    return () => {
      eventSource.removeEventListener("open", handleOpen);
      eventSource.removeEventListener("status", handleStatus);
      eventSource.removeEventListener("notification", handleNotification);
      eventSource.removeEventListener("error", handleError);
      eventSource.removeEventListener("ping", handlePing);
      eventSource.close();
      eventSourceRef.current = null;
      setStatus("closed");
    };
  }, [mergeNotifications]);

  // Dismiss single notification
  const dismiss = useCallback(async (id: string) => {
    try {
      const response = await fetch("/api/notifications/intraday/dismiss", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({ notificationIds: [id] }),
      });

      if (!response.ok) {
        throw new Error(`Failed to dismiss notification: ${response.statusText}`);
      }

      // Remove from local state
      setNotifications((prev) => prev.filter((n) => n.id !== id));
    } catch (error) {
      console.error("[Intraday Notifications] Failed to dismiss:", error);
      throw error;
    }
  }, []);

  // Dismiss many notifications (debounced)
  const dismissMany = useCallback(async (ids: string[]) => {
    // Add to pending set
    ids.forEach((id) => pendingDismissIdsRef.current.add(id));

    // Clear existing timeout
    if (dismissManyTimeoutRef.current) {
      clearTimeout(dismissManyTimeoutRef.current);
    }

    // Debounce: wait 300ms before sending
    dismissManyTimeoutRef.current = setTimeout(async () => {
      const idsToDismiss = Array.from(pendingDismissIdsRef.current);
      pendingDismissIdsRef.current.clear();

      if (idsToDismiss.length === 0) {
        return;
      }

      try {
        const response = await fetch("/api/notifications/intraday/dismiss", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify({ notificationIds: idsToDismiss }),
        });

        if (!response.ok) {
          throw new Error(`Failed to dismiss notifications: ${response.statusText}`);
        }

        // Remove from local state
        setNotifications((prev) =>
          prev.filter((n) => !idsToDismiss.includes(n.id))
        );
      } catch (error) {
        console.error("[Intraday Notifications] Failed to dismiss many:", error);
        throw error;
      }
    }, 300);
  }, []);

  // Dismiss all notifications
  const dismissAll = useCallback(async () => {
    try {
      const response = await fetch("/api/notifications/intraday/dismiss-all", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error(`Failed to dismiss all: ${response.statusText}`);
      }

      // Clear local state
      setNotifications([]);
    } catch (error) {
      console.error("[Intraday Notifications] Failed to dismiss all:", error);
      throw error;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (dismissManyTimeoutRef.current) {
        clearTimeout(dismissManyTimeoutRef.current);
      }
    };
  }, []);

  return {
    notifications,
    loading,
    dismiss,
    dismissMany,
    dismissAll,
  };
}

