"""Genera un modelo ONNX streaming mínimo para tests (audio + estado)."""
from pathlib import Path
from onnx import TensorProto, helper


def make_streaming_model(path: Path, chunk: int = 256, state_dim: int = 4) -> None:
    audio_in = helper.make_tensor_value_info("audio", TensorProto.FLOAT, [1, chunk])
    state_in = helper.make_tensor_value_info("state_in", TensorProto.FLOAT, [1, state_dim])
    audio_out = helper.make_tensor_value_info("enhanced", TensorProto.FLOAT, [1, chunk])
    state_out = helper.make_tensor_value_info("state_out", TensorProto.FLOAT, [1, state_dim])

    half = helper.make_tensor("half", TensorProto.FLOAT, [], [0.5])
    one = helper.make_tensor("one", TensorProto.FLOAT, [], [1.0])
    zero_idx = helper.make_tensor("zero_idx", TensorProto.INT64, [1], [0])

    nodes = [
        # enhanced = audio * 0.5 + state_in[0,0]
        helper.make_node("Mul", ["audio", "half"], ["scaled"]),
        helper.make_node("Gather", ["state_in", "zero_idx"], ["s_row"], axis=0),
        helper.make_node("Gather", ["s_row", "zero_idx"], ["s_elem"], axis=1),
        helper.make_node("Add", ["scaled", "s_elem"], ["enhanced"]),
        # state_out = state_in + 1
        helper.make_node("Add", ["state_in", "one"], ["state_out"]),
    ]
    graph = helper.make_graph(
        nodes, "stfu_test_stream", [audio_in, state_in], [audio_out, state_out],
        initializer=[half, one, zero_idx],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    path.write_bytes(model.SerializeToString())
