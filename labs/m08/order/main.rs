mod order;

use order::{Order, Status, WIRE_LEN};
use std::error::Error;
use std::ffi::OsString;
use std::io::{self, Read, Write};
use std::process::ExitCode;

const USAGE: &str = "USAGE: order encode ID open|cancelled UNITS   OR   order decode";

fn argument(args: &mut impl Iterator<Item = OsString>) -> Result<String, &'static str> {
    args.next().ok_or(USAGE)?.into_string()
        .map_err(|_| "ARG expected=UTF-8")
}

fn read_order(mut input: impl Read) -> Result<Order, Box<dyn Error>> {
    // The thirteenth byte already proves the record is too long.
    let mut buf = [0u8; WIRE_LEN + 1];
    let mut n = 0;
    while n < buf.len() {
        match input.read(&mut buf[n..]) {
            Ok(0) => break,
            Ok(count) => n += count,
            Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
            Err(err) => return Err(err.into()),
        }
    }
    Ok(Order::decode(&buf[..n])?)
}

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    match argument(&mut args)?.as_str() {
        "encode" => {
            let id = argument(&mut args)?.parse::<u16>()
                .map_err(|_| "ID expected=u16")?;
            let status = match argument(&mut args)?.as_str() {
                "open" => Status::Open,
                "cancelled" => Status::Cancelled,
                _ => return Err("STATUS expected=open|cancelled".into()),
            };
            let units = argument(&mut args)?.parse::<u64>()
                .map_err(|_| "UNITS expected=u64")?;
            if args.next().is_some() {
                return Err(USAGE.into());
            }
            let order = Order { id, status, units };
            let mut out = io::stdout().lock();
            out.write_all(&order.encode())?;
            out.flush()?;
        }
        "decode" => {
            if args.next().is_some() {
                return Err(USAGE.into());
            }
            let order = read_order(io::stdin().lock())?;
            writeln!(io::stdout().lock(), "id={} status={:?} units={}",
                     order.id, order.status, order.units)?;
        }
        _ => return Err(USAGE.into()),
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("REJECT {err}");
            ExitCode::from(2)
        }
    }
}
