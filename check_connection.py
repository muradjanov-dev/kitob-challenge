import asyncio

async def write_to_connection(writer, data):
    if writer.is_closing():
        print("Connection is closed, cannot write data.")
        return
    try:
        writer.writelines(data)
        await writer.drain()  # Ensure data is sent before moving on
    except Exception as e:
        print(f"Failed to write data: {e}")

async def main():
    reader, writer = await asyncio.open_connection('127.0.0.1', 6379)
    try:
        await write_to_connection(writer, [b'Hello', b'World'])
    finally:
        writer.close()
        await writer.wait_closed()

asyncio.run(main())
