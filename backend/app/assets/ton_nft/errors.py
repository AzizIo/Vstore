"""Typed failures raised by TON NFT data providers."""

class TONNFTError(Exception):
    """Base class for expected TON NFT verification errors."""

class ProviderUnavailable(TONNFTError):
    """The upstream provider could not be reached or returned a server error."""

class InvalidProviderData(TONNFTError):
    """The provider returned a response that cannot be trusted or parsed."""

class UnsupportedAsset(TONNFTError):
    """The provider explicitly identifies the contract as unsupported."""
