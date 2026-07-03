use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_log::{Target, TargetKind};

struct BackendProcess(Mutex<Option<Child>>);

fn backend_command() -> Option<Command> {
    // 1) binario empaquetado junto al exe (build de instalador)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let packaged = dir.join("stfu-backend.exe");
            if packaged.exists() {
                log::info!("backend: usando binario empaquetado {:?}", packaged);
                return Some(Command::new(packaged));
            }
        }
    }
    // 2) modo dev: venv del repo (ruta fijada en compile-time, solo existe en dev)
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let python = repo.join("backend/.venv/Scripts/python.exe");
    if python.exists() {
        log::info!("backend: usando venv dev {:?}", python);
        let mut cmd = Command::new(python);
        cmd.args(["-m", "uvicorn", "stfu.main:app", "--port", "8765"])
            .current_dir(repo.join("backend"));
        return Some(cmd);
    }
    None
}

fn spawn_backend(state: &BackendProcess) {
    let Some(mut cmd) = backend_command() else {
        log::warn!("backend no encontrado (ni empaquetado ni venv dev) — inicia uvicorn manualmente");
        return;
    };
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    match cmd.spawn() {
        Ok(child) => {
            log::info!("backend iniciado pid={}", child.id());
            *state.0.lock().unwrap() = Some(child);
        }
        Err(e) => log::error!("no se pudo iniciar el backend: {e}"),
    }
}

fn kill_backend(state: &BackendProcess) {
    if let Some(mut child) = state.0.lock().unwrap().take() {
        log::info!("deteniendo backend pid={}", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn setup_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Abrir STFU", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Salir", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit])?;
    TrayIconBuilder::with_id("stfu-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("STFU — noise cancellation")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            }
            "quit" => {
                kill_backend(app.state::<BackendProcess>().inner());
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_log::Builder::new()
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir { file_name: Some("stfu-ui".into()) }),
                ])
                .level(log::LevelFilter::Info)
                .build(),
        )
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            spawn_backend(app.state::<BackendProcess>().inner());
            setup_tray(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // cerrar la ventana esconde a tray; el audio sigue procesando
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            kill_backend(app_handle.state::<BackendProcess>().inner());
        }
    });
}
