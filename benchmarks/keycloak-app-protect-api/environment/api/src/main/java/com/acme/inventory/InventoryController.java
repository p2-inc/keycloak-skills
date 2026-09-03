// Copyright 2026 Phase Two, Inc.
// SPDX-License-Identifier: Apache-2.0
package com.acme.inventory;

import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InventoryController {

    /** Liveness probe. The monitoring system calls this unauthenticated. */
    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok");
    }

    @GetMapping("/api/items")
    public List<Map<String, Object>> items() {
        return List.of(
                Map.of("sku", "ACME-001", "name", "Rocket skates", "stock", 42),
                Map.of("sku", "ACME-002", "name", "Portable hole", "stock", 7),
                Map.of("sku", "ACME-003", "name", "Earthquake pills", "stock", 138));
    }

    @GetMapping("/api/admin/audit")
    public List<Map<String, String>> audit() {
        return List.of(
                Map.of("at", "2026-08-30T09:12:44Z", "who", "alice", "action", "stock-adjust ACME-002 -1"),
                Map.of("at", "2026-08-29T16:03:10Z", "who", "alice", "action", "sku-create ACME-003"));
    }
}
