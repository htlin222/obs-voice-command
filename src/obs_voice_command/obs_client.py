"""OBS WebSocket client wrapper for zoom control."""
from dataclasses import dataclass

from obsws_python import ReqClient

from .zoom import Transform

DEFAULT_TIMEOUT = 5.0  # 每個 WebSocket 請求的逾時秒數；沒有逾時 OBS 卡住會讓執行緒永久掛起


@dataclass(frozen=True)
class SceneItem:
    """Scene item source info."""

    scene_name: str
    item_id: int
    source_width: float
    source_height: float


class ObsClient:
    """OBS WebSocket client with zoom-control-specific methods.

    Connection is deferred until connect() is called to allow
    graceful error handling and reconnection logic in main.py.
    """

    def __init__(self, host: str, port: int, password: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Store connection parameters for later connection."""
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._client: ReqClient | None = None

    def connect(self) -> None:
        """Create ReqClient and authenticate with OBS.

        Any previous connection is closed first so reconnects don't leak sockets.

        Raises:
            ConnectionError: If connection fails. Message includes
                troubleshooting hints about OBS running, WebSocket
                server enabled, and password correctness.
        """
        self.disconnect()
        try:
            self._client = ReqClient(
                host=self.host, port=self.port, password=self.password, timeout=self.timeout
            )
        except Exception as e:  # 底層可能丟 OBSSDKError / OSError / WebSocketException / ValueError
            raise ConnectionError(
                f"Failed to connect to OBS at {self.host}:{self.port}. "
                f"Ensure: (1) OBS is running, (2) WebSocket server is enabled in "
                f"Tools → WebSocket Server Settings, (3) password is correct. "
                f"Error: {type(e).__name__}: {e}"
            ) from e

    def disconnect(self) -> None:
        """Close the underlying WebSocket if open. Safe to call repeatedly."""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass

    def _require(self) -> ReqClient:
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._client

    def get_canvas_size(self) -> tuple[float, float]:
        """Get canvas (base resolution) size in pixels.

        Returns:
            Tuple of (width, height).
        """
        video_settings = self._require().get_video_settings()
        return (float(video_settings.base_width), float(video_settings.base_height))

    def find_display_capture(self, scene: str, source: str) -> SceneItem:
        """Find display capture source in scene.

        Args:
            scene: Scene name. If empty string, uses current program scene.
            source: Source name to find. If empty string, finds first
                display_capture or screen_capture input.

        Returns:
            SceneItem with source dimensions.

        Raises:
            RuntimeError: If source not found. Error message lists all
                available sources in the scene.
        """
        client = self._require()

        if not scene:
            scene_result = client.get_current_program_scene()
            scene = scene_result.scene_name

        items_result = client.get_scene_item_list(scene)
        scene_items: list[dict] = items_result.scene_items or []

        target_item = None

        if source:
            for item in scene_items:
                if item.get("sourceName") == source:
                    target_item = item
                    break
        else:
            for item in scene_items:
                input_kind = (item.get("inputKind") or "").lower()
                if "display_capture" in input_kind or "screen_capture" in input_kind:
                    target_item = item
                    break

        if not target_item:
            available = [str(item.get("sourceName", "?")) for item in scene_items]
            raise RuntimeError(
                f"Display capture source not found in scene '{scene}'. "
                f"Available sources: {', '.join(available)}"
            )

        item_id = target_item.get("sceneItemId")
        if not isinstance(item_id, int):
            raise RuntimeError(f"OBS 回傳的 scene item 沒有 sceneItemId: {target_item}")
        transform_result = client.get_scene_item_transform(scene, item_id)
        transform_data: dict = transform_result.scene_item_transform or {}

        width = float(transform_data.get("sourceWidth") or 0)
        height = float(transform_data.get("sourceHeight") or 0)
        if width <= 0 or height <= 0:
            raise RuntimeError(
                f"Source '{target_item.get('sourceName')}' 尺寸為 {width}x{height}，"
                "無法計算縮放；請確認該來源已有畫面（螢幕擷取權限、顯示器已選）"
            )

        return SceneItem(
            scene_name=scene,
            item_id=item_id,
            source_width=width,
            source_height=height,
        )

    def get_transform(self, item: SceneItem) -> Transform:
        """Get current scene item transform.

        Args:
            item: Scene item to read transform from.

        Returns:
            Transform with position and scale.
        """
        transform_result = self._require().get_scene_item_transform(item.scene_name, item.item_id)
        transform_data: dict = transform_result.scene_item_transform or {}

        return Transform(
            pos_x=float(transform_data.get("positionX", 0)),
            pos_y=float(transform_data.get("positionY", 0)),
            scale_x=float(transform_data.get("scaleX", 1)),
            scale_y=float(transform_data.get("scaleY", 1)),
        )

    def set_transform(self, item: SceneItem, t: Transform) -> None:
        """Set scene item transform.

        Args:
            item: Scene item to update.
            t: Transform with new position and scale.
        """
        self._require().set_scene_item_transform(
            item.scene_name,
            item.item_id,
            {
                "positionX": t.pos_x,
                "positionY": t.pos_y,
                "scaleX": t.scale_x,
                "scaleY": t.scale_y,
            },
        )
