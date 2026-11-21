"""Testes do registro de armazenamento (§5)."""

from __future__ import annotations

from app.services.storage_registry import StorageRegistry, VolumeRecord, VolumeState


async def test_upsert_and_get(tmp_path):
    registry = StorageRegistry(data_dir=str(tmp_path))
    await registry.upsert(
        VolumeRecord(volume_id=42, machine_id=555, capacity_gb=100.0, mount_path="/data")
    )
    record = await registry.get(42)
    assert record.machine_id == 555
    assert record.state is VolumeState.UNKNOWN


async def test_persistence_across_instances(tmp_path):
    registry1 = StorageRegistry(data_dir=str(tmp_path))
    await registry1.upsert(VolumeRecord(volume_id=7, machine_id=9, capacity_gb=50.0))
    registry2 = StorageRegistry(data_dir=str(tmp_path))
    record = await registry2.get(7)
    assert record is not None
    assert record.capacity_gb == 50.0


async def test_for_host_filters_active_only(tmp_path):
    registry = StorageRegistry(data_dir=str(tmp_path))
    await registry.upsert(VolumeRecord(volume_id=1, machine_id=555, capacity_gb=10.0, state=VolumeState.AVAILABLE))
    await registry.upsert(VolumeRecord(volume_id=2, machine_id=555, capacity_gb=10.0, state=VolumeState.HOST_UNAVAILABLE))
    await registry.upsert(VolumeRecord(volume_id=3, machine_id=999, capacity_gb=10.0, state=VolumeState.AVAILABLE))
    records = await registry.for_host(555)
    assert [r.volume_id for r in records] == [1]


async def test_mark_state_and_usage(tmp_path):
    registry = StorageRegistry(data_dir=str(tmp_path))
    await registry.upsert(VolumeRecord(volume_id=1, machine_id=555, capacity_gb=100.0))
    await registry.mark_state(1, VolumeState.IN_USE, note="sessão ativa")
    await registry.update_usage(1, 37.5)
    record = await registry.get(1)
    assert record.state is VolumeState.IN_USE
    assert record.used_gb == 37.5


async def test_public_representation(tmp_path):
    registry = StorageRegistry(data_dir=str(tmp_path))
    await registry.upsert(VolumeRecord(volume_id=1, machine_id=555, capacity_gb=100.0, used_gb=25.0))
    record = await registry.get(1)
    public = registry.to_public(record)
    assert public["free_gb"] == 75.0
    assert public["mount_path"] == "/data"
    assert "state" in public
