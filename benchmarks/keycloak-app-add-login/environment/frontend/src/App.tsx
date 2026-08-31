// Copyright 2026 Phase Two, Inc.
// SPDX-License-Identifier: Apache-2.0

// The Acme customer portal.
//
// There is no authentication here yet: every visitor sees the same page and the
// portal has no idea who they are. Wiring that up is the task.
export function App() {
    return (
        <main>
            <h1>Acme Portal</h1>
            <p>Welcome to the Acme customer portal.</p>
        </main>
    );
}
