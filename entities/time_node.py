import logging

logger = logging.getLogger(__name__)

class TimeNode:
    """
    Represents a party in the protocol (Alice or Bob).
    Maintains a local clock with an offset from the true time.
    """
    def __init__(self, name: str, initial_offset: float = 0.0):
        self.name = name
        self.clock_offset = initial_offset

    def get_local_time(self, true_time: float, intentional_shift: float = 0.0) -> float:
        """
        Returns the local time based on the true scheduled time.
        Allows adding an intentional shift for correlation probing.
        """
        return true_time + self.clock_offset + intentional_shift

    def adjust_clock(self, adjustment: float):
        """
        Adjusts the internal clock offset by the given amount.
        """
        self.clock_offset += adjustment
        logger.info(f"{self.name}: Adjusted clock by {adjustment:+.4f}. New offset: {self.clock_offset:+.4f}")
