use std::fmt;

pub const WIRE_LEN: usize = 12;
const VERSION: u8 = 1;
const OPEN_TAG: u8 = 0x10;
const CANCELLED_TAG: u8 = 0x20;

#[derive(Debug)]
pub enum Status {
    Open,
    Cancelled,
}

impl Status {
    fn tag(&self) -> u8 {
        match self {
            Self::Open => OPEN_TAG,
            Self::Cancelled => CANCELLED_TAG,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, DecodeError> {
        match tag {
            OPEN_TAG => Ok(Self::Open),
            CANCELLED_TAG => Ok(Self::Cancelled),
            other => Err(DecodeError::Status(other)),
        }
    }
}

pub struct Order {
    pub id: u16,
    pub status: Status,
    pub units: u64,
}

impl Order {
    pub fn encode(&self) -> [u8; WIRE_LEN] {
        let mut out = [0; WIRE_LEN];
        out[0] = VERSION;
        out[1] = self.status.tag();
        out[2..4].copy_from_slice(&self.id.to_le_bytes());
        out[4..].copy_from_slice(&self.units.to_le_bytes());
        out
    }

    pub fn decode(raw: &[u8]) -> Result<Self, DecodeError> {
        let frame: &[u8; WIRE_LEN] = raw.try_into().map_err(|_| DecodeError::Length(raw.len()))?;
        let &[version, tag, lo, hi, units @ ..] = frame;
        if version != VERSION {
            return Err(DecodeError::Version(version));
        }
        let status = Status::from_tag(tag)?;
        Ok(Self {
            id: u16::from_le_bytes([lo, hi]),
            status,
            units: u64::from_le_bytes(units),
        })
    }
}

#[derive(Debug)]
pub enum DecodeError {
    Length(usize),
    Version(u8),
    Status(u8),
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Length(n) => write!(f, "LENGTH expected={WIRE_LEN} bytes_seen={n}"),
            Self::Version(v) => write!(f, "VERSION got={v:#04x}"),
            Self::Status(tag) => write!(f, "STATUS tag={tag:#04x}"),
        }
    }
}

impl std::error::Error for DecodeError {}
