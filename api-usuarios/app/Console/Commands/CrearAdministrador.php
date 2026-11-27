<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Models\User;
use Illuminate\Console\Command;
use Illuminate\Database\QueryException;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Validator;
use Illuminate\Support\Str;
use Throwable;

class CrearAdministrador extends Command
{
    protected $signature = 'usuarios:crear-admin';

    protected $description =
        'Crea una cuenta de administrador de forma controlada.';

    public function handle(): int
    {
        if (! $this->input->isInteractive()) {
            $this->error(
                'Este comando requiere una terminal interactiva.'
            );

            return self::FAILURE;
        }

        $this->info('Creacion de administrador');
        $this->newLine();

        $nombre = trim((string) $this->ask(
            'Nombre del administrador'
        ));

        $correo = Str::lower(trim((string) $this->ask(
            'Correo electronico'
        )));

        $contrasena = $this->secret(
            'Contrasena (minimo 12 caracteres)',
            false
        );

        $confirmacion = $this->secret(
            'Confirma la contrasena',
            false
        );

        $validator = Validator::make(
            [
                'nombre' => $nombre,
                'correo' => $correo,
                'contrasena' => $contrasena,
                'contrasena_confirmation' => $confirmacion,
            ],
            [
                'nombre' => [
                    'required',
                    'string',
                    'min:1',
                    'max:120',
                    'not_regex:/\x00/',
                ],
                'correo' => [
                    'required',
                    'string',
                    'email:rfc',
                    'max:254',
                    'not_regex:/\x00/',
                ],
                'contrasena' => [
                    'required',
                    'string',
                    'min:12',
                    'max:128',
                    'confirmed',
                ],
            ]
        );

        if ($validator->fails()) {
            foreach ($validator->errors()->all() as $error) {
                $this->error($error);
            }

            return self::FAILURE;
        }

        try {
            if (User::where('correo', $correo)->exists()) {
                $this->error(
                    'El correo ya pertenece a una cuenta existente.'
                );

                return self::FAILURE;
            }

            $this->newLine();

            $this->table(
                ['Campo', 'Valor'],
                [
                    ['Nombre', $nombre],
                    ['Correo', $correo],
                    ['Rol', 'admin'],
                ]
            );

            if (! $this->confirm(
                'Confirmas la creacion del administrador?',
                false
            )) {
                $this->warn('Operacion cancelada.');

                return self::FAILURE;
            }

            $user = new User();

            $user->nombre = $nombre;
            $user->correo = $correo;
            $user->password = Hash::make($contrasena);
            $user->role = 'admin';

            $user->save();

        } catch (QueryException $exception) {
            if (
                ($exception->errorInfo[0] ?? null) === '23505'
                && str_contains(
                    $exception->errorInfo[2] ?? '',
                    'usuarios_correo_unique'
                )
            ) {
                $this->error('El correo ya esta registrado.');
            } else {
                $this->error(
                    'No se pudo guardar el administrador.'
                );
            }

            return self::FAILURE;

        } catch (Throwable) {
            $this->error(
                'No se pudo completar la operacion.'
            );

            return self::FAILURE;
        }

        $this->newLine();

        $this->info('Administrador creado correctamente.');

        $this->table(
            ['Campo', 'Valor'],
            [
                ['ID', $user->id],
                ['Nombre', $user->nombre],
                ['Correo', $user->correo],
                ['Rol', $user->role],
            ]
        );

        return self::SUCCESS;
    }
}
