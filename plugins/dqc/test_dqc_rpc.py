import os
import sys
import json
import asyncio
from quantnet_mq.rpcclient import RPCClient
from quantnet_mq.schema.models import Schema


class MyDQC:
    def __init__(self, schedule_file):
        self._schedule_file = schedule_file

    async def do_dqc(self):
        with open(self._schedule_file, "r") as f:
            commands = json.load(f)

        # Structure the payload as expected by DQCRequest
        msg = {"commands": commands}

        print(f"Sending DQC request with {len(commands)} commands...")
        return json.loads(await self._client.call("dqcRequest", msg, timeout=60.0))

    async def main(self):
        # Adjusted path to match directory structure
        schema_path = os.path.join(os.path.dirname(__file__), "../schema/dqc.yaml")
        Schema.load_schema(schema_path, ns="dqc")

        self._client = RPCClient("dqc-client", host=os.getenv("HOST", "localhost"))
        self._client.set_handler("dqcRequest", None, "quantnet_mq.schema.models.dqc.dqcRequest")

        await self._client.start()

        try:
            ret = await self.do_dqc()
            print("Response received:")
            print(json.dumps(ret, indent=2))
        except Exception as e:
            print(f"Error during DQC call: {e}")


if __name__ == "__main__":
    schedule_file = sys.argv[1] if len(sys.argv) > 1 else "../qnpack/qnpack/dqc_sim/timeslot_schedule.json"

    if not os.path.exists(schedule_file):
        print(f"Error: Schedule file not found at {schedule_file}")
        sys.exit(1)

    asyncio.run(MyDQC(schedule_file).main())
