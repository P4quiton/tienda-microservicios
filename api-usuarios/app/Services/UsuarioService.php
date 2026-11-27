<?php

declare(strict_types=1);

namespace App\Services;

use App\Exceptions\CorreoDuplicadoException;
use App\Exceptions\CredencialesInvalidasException;
use App\Models\User;
use Illuminate\Database\QueryException;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Str;

class UsuarioService
{
    public function register(array $data): User
    {
        $correo = Str::lower(trim($data['correo']));

        if (User::where('correo', $correo)->exists()) {
            throw new CorreoDuplicadoException(
                'El correo ya está registrado.'
            );
        }

        $user = new User();

        $user->nombre = trim($data['nombre']);
        $user->correo = $correo;
        $user->password = Hash::make($data['contrasena']);
        $user->role = 'cliente';

        try {
            $user->save();
        } catch (QueryException $exception) {
            if (
                ($exception->errorInfo[0] ?? null) === '23505'
                && str_contains(
                    $exception->errorInfo[2] ?? '',
                    'usuarios_correo_unique'
                )
            ) {
                throw new CorreoDuplicadoException(
                    'El correo ya está registrado.'
                );
            }

            throw $exception;
        }

        return $user;
    }

    public function authenticate(array $data): User
    {
        $correo = Str::lower(trim($data['correo']));
        $contrasena = $data['contrasena'];

        $user = User::where('correo', $correo)->first();

        if ($user === null) {
            // Realizar una operación de hashing incluso
            // cuando el usuario no existe.
            Hash::make(bin2hex(random_bytes(32)));

            throw new CredencialesInvalidasException(
                'Credenciales inválidas.'
            );
        }

        if (! Hash::check($contrasena, $user->password)) {
            throw new CredencialesInvalidasException(
                'Credenciales inválidas.'
            );
        }

        if (Hash::needsRehash($user->password)) {
            $user->password = Hash::make($contrasena);
            $user->save();
        }

        return $user;
    }

    public function findById(string $id): ?User
    {
        return User::find($id);
    }
}
