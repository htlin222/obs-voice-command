"""OBS WebSocket client wrapper for zoom control."""
from dataclasses import dataclass

from obsws_python import ReqClient
from obsws_python.error import OBSSDKError

from .zoom import Transform


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

    def __init__(self, host: str, port: int, password: str) -> None:
        """Store connection parameters for later connection."""
        self.host = host
        self.port = port
        self.password = password
        self._client: ReqClient | None = None

    def connect(self) -> None:
        """Create ReqClient and authenticate with OBS.

        Raises:
            ConnectionError: If connection fails. Message includes
                troubleshooting hints about OBS running, WebSocket
                server enabled, and password correctness.
        """
        try:
            self._client = ReqClient(
                host=self.host, port=self.port, password=self.password
            )
        except (OBSSDKError, ConnectionRefusedError, TimeoutError) as e:
            raise ConnectionError(
                f"Failed to connect to OBS at {self.host}:{self.port}. "
                f"Ensure: (1) OBS is running, (2) WebSocket server is enabled in "
                f"Tools → WebSocket Server Settings, (3) password is correct. "
                f"Error: {e}"
            ) from e

    def get_canvas_size(self) -> tuple[float, float]:
        """Get canvas (base resolution) size in pixels.

        Returns:
            Tuple of (width, height).
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        video_settings = self._client.get_video_settings()
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
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        if not scene:
            scene_result = self._client.get_current_program_scene()
            scene = scene_result.scene_name

        items_result = self._client.get_scene_item_list(scene)
        scene_items: list[dict] = items_result.scene_items

        target_item = None

        if source:
            for item in scene_items:
                if item.get("sourceName") == source:
                    target_item = item
                    break
        else:
            for item in scene_items:
                input_kind = item.get("inputKind", "").lower()
                if "display_capture" in input_kind or "screen_capture" in input_kind:
                    target_item = item
                    break

        if not target_item:
            available = [item.get("sourceName", "?") for item in scene_items]
            raise RuntimeError(
                f"Display capture source not found in scene '{scene}'. "
                f"Available sources: {', '.join(available)}"
            )

        item_id = target_item.get("sceneItemId")
        transform_result = self._client.get_scene_item_transform(scene, item_id)
        transform_data: dict = transform_result.scene_item_transform

        return SceneItem(
            scene_name=scene,
            item_id=item_id,
            source_width=float(transform_data.get("sourceWidth", 0)),
            source_height=float(transform_data.get("sourceHeight", 0)),
        )

    def get_transform(self, item: SceneItem) -> Transform:
        """Get current scene item transform.

        Args:
            item: Scene item to read transform from.

        Returns:
            Transform with position and scale.
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        transform_result = self._client.get_scene_item_transform(item.scene_name, item.item_id)
        transform_data: dict = transform_result.scene_item_transform

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
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        self._client.set_scene_item_transform(
            item.scene_name,
            item.item_id,
            {
                "positionX": t.pos_x,
                "positionY": t.pos_y,
                "scaleX": t.scale_x,
                "scaleY": t.scale_y,
            },
        )
